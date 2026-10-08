"""Admin dashboard figures, computed live from Postgres over whole UTC days (spec §6.5)."""

from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation, Message
from app.guardrails.models import GuardrailEvent, UsageRecord


class Totals(BaseModel):
    questions: int
    active_users: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    thumbs_up_rate: float | None
    not_found_rate: float | None
    low_confidence_rate: float | None
    guardrail_blocks: int


class DailyPoint(BaseModel):
    date: date
    questions: int = 0
    cost_usd: float = 0.0
    not_found: int = 0
    low_confidence: int = 0
    blocked: int = 0


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _day(column: object) -> object:
    return cast(func.timezone("UTC", column), Date)


async def summary(
    session: AsyncSession, days: int, now: datetime | None = None
) -> tuple[Totals, list[DailyPoint]]:
    now = now or datetime.now(UTC)
    first = (now - timedelta(days=days - 1)).date()
    since = datetime.combine(first, time.min, tzinfo=UTC)
    answers = (Message.role == "assistant") & (Message.created_at >= since)

    day = _day(Message.created_at).label("day")
    per_day = await session.execute(
        select(
            day,
            func.count(),
            func.count().filter(Message.outcome == "not_found"),
            func.count().filter(Message.low_confidence.is_(True)),
            func.count().filter(Message.outcome == "blocked"),
        )
        .where(answers)
        .group_by(day)
    )
    points = {
        first + timedelta(days=i): DailyPoint(date=first + timedelta(days=i)) for i in range(days)
    }
    for when, questions, not_found, low, blocked in per_day.all():
        if when in points:
            point = points[when]
            point.questions, point.not_found = questions, not_found
            point.low_confidence, point.blocked = low, blocked

    cost_day = _day(UsageRecord.created_at).label("day")
    for when, cost in (
        await session.execute(
            select(cost_day, func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
            .where(UsageRecord.created_at >= since)
            .group_by(cost_day)
        )
    ).all():
        if when in points:
            points[when].cost_usd = round(float(cost), 6)

    counts = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Message.outcome == "answered"),
                func.count().filter(Message.outcome == "not_found"),
                func.count().filter(
                    (Message.outcome == "answered") & Message.low_confidence.is_(True)
                ),
                func.count().filter(Message.feedback_rating == 1),
                func.count().filter(Message.feedback_rating.is_not(None)),
                func.count(func.distinct(Conversation.user_id)),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(answers)
        )
    ).one()
    questions, answered, not_found, low, thumbs_up, rated, active = counts
    usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
            ).where(UsageRecord.created_at >= since)
        )
    ).one()
    blocks = await session.scalar(
        select(func.count()).where(
            GuardrailEvent.action == "blocked", GuardrailEvent.created_at >= since
        )
    )
    totals = Totals(
        questions=questions,
        active_users=active,
        input_tokens=int(usage[0]),
        output_tokens=int(usage[1]),
        cost_usd=round(float(usage[2]), 6),
        thumbs_up_rate=_rate(thumbs_up, rated),
        not_found_rate=_rate(not_found, questions),
        low_confidence_rate=_rate(low, answered),
        guardrail_blocks=blocks or 0,
    )
    return totals, [points[d] for d in sorted(points)]
