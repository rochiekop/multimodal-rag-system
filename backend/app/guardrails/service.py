"""Guardrail events, strikes, chat locks and admin notifications.
Functions flush but never commit; callers commit."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.guardrails.models import GuardrailEvent, Notification
from app.guardrails.settings import GuardrailSettings
from app.users.models import User

LIST_LIMIT = 200


@dataclass(frozen=True)
class StrikeResult:
    strikes: int
    locked_until: datetime | None


class NotificationNotFound(Exception):
    code = "not_found"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def notify(
    session: AsyncSession,
    *,
    kind: str,
    title: str,
    body: str = "",
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Add an admin notification; a repeated dedupe_key is silently ignored."""
    statement = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            kind=kind,
            title=title,
            body=body,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    await session.execute(statement)


async def _strike_count(session: AsyncSession, user_id: uuid.UUID, since: datetime) -> int:
    reset_at = await session.scalar(select(User.strike_reset_at).where(User.id == user_id))
    if reset_at is not None and reset_at > since:
        since = reset_at
    query = select(func.count()).where(
        GuardrailEvent.user_id == user_id,
        GuardrailEvent.strike.is_(True),
        GuardrailEvent.created_at >= since,
    )
    return int(await session.scalar(query) or 0)


async def record_event(
    session: AsyncSession,
    *,
    user: User,
    check: str,
    action: str,
    settings: GuardrailSettings,
    category: str | None = None,
    strike: bool = False,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> StrikeResult:
    """Store and audit one block or flag. A strike that reaches the limit locks chat."""
    session.add(
        GuardrailEvent(
            user_id=user.id,
            conversation_id=conversation_id,
            message_id=message_id,
            check=check,
            category=category,
            action=action,
            strike=strike,
            detail=detail or {},
        )
    )
    await session.flush()
    await audit.record(
        session,
        action=f"guardrail.{action}",
        actor=user,
        target_type="user",
        target_id=user.id,
        detail={"check": check, "category": category, "strike": strike, **(detail or {})},
    )
    if not strike:
        return StrikeResult(strikes=0, locked_until=None)

    now = datetime.now(UTC)
    strikes = await _strike_count(
        session, user.id, now - timedelta(hours=settings.strike_window_hours)
    )
    if strikes < settings.strike_limit:
        return StrikeResult(strikes=strikes, locked_until=None)

    locked_until = now + timedelta(hours=settings.strike_lock_hours)
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(chat_locked_until=locked_until, strike_reset_at=now)
    )
    await audit.record(
        session,
        action="guardrail.strike_lock",
        actor=user,
        target_type="user",
        target_id=user.id,
        detail={"strikes": strikes, "locked_until": locked_until.isoformat()},
    )
    await notify(
        session,
        kind="strike_lock",
        title=f"{user.username} was locked after {strikes} guardrail violations",
        body=f"Chat is locked until {locked_until:%Y-%m-%d %H:%M} UTC. Unlock from Users.",
        target_type="user",
        target_id=user.id,
        # Concurrent final strikes lock the same user in the same hour: notify once.
        dedupe_key=f"strike_lock:{user.id}:{locked_until:%Y%m%d%H}",
    )
    return StrikeResult(strikes=strikes, locked_until=locked_until)


async def list_notifications(
    session: AsyncSession, unread_only: bool = False
) -> list[Notification]:
    query = select(Notification).order_by(Notification.seq.desc())
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return list((await session.scalars(query.limit(LIST_LIMIT))).all())


async def mark_read(session: AsyncSession, notification_id: uuid.UUID) -> Notification:
    notification = await session.get(Notification, notification_id)
    if notification is None:
        raise NotificationNotFound("Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.flush()
    return notification
