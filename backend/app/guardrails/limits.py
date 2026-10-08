"""Checks that run before a question is accepted: chat lock, question length, per-user rate
limit (Redis) and daily cost caps (from usage_records)."""

import logging
import time
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.guardrails.models import UsageRecord
from app.guardrails.service import notify
from app.guardrails.settings import GuardrailSettings
from app.users.models import User

logger = logging.getLogger(__name__)


class GuardrailRefusal(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class RateLimiter:
    """Fixed one-minute windows. If Redis is down, requests are allowed (logged)."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                count, _ = await pipe.incr(bucket).expire(bucket, window_seconds).execute()  # type: ignore[union-attr]  # redis-py types incr() as Awaitable | Any
        except (RedisError, OSError):
            logger.warning("Rate limiter unavailable; allowing the request", exc_info=True)
            return True
        return int(count) <= limit


def _today() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def spent_today(session: AsyncSession, user_id: uuid.UUID | None = None) -> float:
    query = select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
        UsageRecord.created_at >= _today()
    )
    if user_id is not None:
        query = query.where(UsageRecord.user_id == user_id)
    return float(await session.scalar(query) or 0.0)


async def _check_cap(
    session: AsyncSession,
    *,
    spent: float,
    cap: float,
    ratio: float,
    alert_key: str,
    alert_title: str,
    target_id: uuid.UUID | None,
) -> bool:
    """True if the cap is reached. Notifies admins once per day when spend nears the cap."""
    if cap <= 0:
        return False
    if spent >= cap * ratio:
        await notify(
            session,
            kind="cost_alert",
            title=alert_title,
            body=f"${spent:.2f} of the ${cap:.2f} daily limit used.",
            target_type="user" if target_id else "installation",
            target_id=target_id,
            dedupe_key=f"{alert_key}:{_today():%Y-%m-%d}",
        )
    return spent >= cap


async def check_chat_allowed(
    session: AsyncSession,
    limiter: RateLimiter,
    user: User,
    settings: GuardrailSettings,
    question: str,
) -> None:
    """Raise GuardrailRefusal when the question must not be processed. Notifications it adds
    are flushed into the caller's transaction; the caller commits."""
    now = datetime.now(UTC)
    if user.chat_locked_until is not None and user.chat_locked_until > now:
        raise GuardrailRefusal(
            423,
            "chat_locked",
            "Your chat access is temporarily locked after repeated policy violations. "
            f"Try again after {user.chat_locked_until:%Y-%m-%d %H:%M} UTC "
            "or contact an administrator.",
        )
    if len(question) > settings.max_question_chars:
        raise GuardrailRefusal(
            422,
            "question_too_long",
            f"Questions can be at most {settings.max_question_chars} characters.",
        )
    if not await limiter.hit(f"user:{user.id}", settings.rate_limit_per_minute):
        raise GuardrailRefusal(
            429, "rate_limited", "You're sending questions too quickly. Wait a minute."
        )
    installation_spent = await spent_today(session)
    if await _check_cap(
        session,
        spent=installation_spent,
        cap=settings.installation_daily_cost_usd,
        ratio=settings.cost_alert_ratio,
        alert_key="cost_alert:installation",
        alert_title="Installation is near its daily AI spending limit",
        target_id=None,
    ):
        raise GuardrailRefusal(
            429, "service_limit_reached", "The assistant has reached today's usage limit."
        )
    user_spent = await spent_today(session, user.id)
    if await _check_cap(
        session,
        spent=user_spent,
        cap=settings.user_daily_cost_usd,
        ratio=settings.cost_alert_ratio,
        alert_key=f"cost_alert:user:{user.id}",
        alert_title=f"{user.username} is near their daily AI spending limit",
        target_id=user.id,
    ):
        raise GuardrailRefusal(
            429, "daily_limit_reached", "You've reached today's usage limit. Try again tomorrow."
        )
