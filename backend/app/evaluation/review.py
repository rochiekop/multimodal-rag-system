"""Review queue (spec §6.5): 👎 answers, low-confidence answers and guardrail events.
Admins see conversation content only here, and every view is audited (spec §6.6).
Functions flush but never commit."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.chat.models import Conversation, Message
from app.evaluation import service as evaluation
from app.evaluation.models import EvalCase
from app.evaluation.schemas import (
    AddToSetIn,
    CaseIn,
    MessageReview,
    ReviewAnswer,
    ReviewItem,
    ReviewUser,
)
from app.guardrails.models import GuardrailEvent
from app.users.models import User

Kind = Literal["feedback", "low_confidence", "guardrail"]
KINDS: tuple[Kind, ...] = ("feedback", "low_confidence", "guardrail")
SNIPPET = 300


async def _question_for(session: AsyncSession, message: Message) -> str | None:
    """The user question this assistant message answered (the user message just before it)."""
    query = (
        select(Message.content)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.role == "user",
            Message.seq < message.seq,
        )
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return await session.scalar(query)


async def _message_items(
    session: AsyncSession, kind: Kind, include_reviewed: bool, limit: int
) -> list[ReviewItem]:
    query = (
        select(Message, User)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .where(Message.role == "assistant")
    )
    if kind == "feedback":
        query = query.where(Message.feedback_rating == -1).order_by(Message.feedback_at.desc())
    else:
        query = query.where(Message.low_confidence.is_(True)).order_by(Message.created_at.desc())
    if not include_reviewed:
        query = query.where(Message.reviewed_at.is_(None))
    items = []
    for message, owner in (await session.execute(query.limit(limit))).all():
        question = await _question_for(session, message)
        items.append(
            ReviewItem(
                kind=kind,
                id=message.id,
                created_at=(message.feedback_at if kind == "feedback" else None)
                or message.created_at,
                user_id=owner.id,
                username=owner.username,
                message_id=message.id,
                question=question[:SNIPPET] if question else None,
                answer=message.content[:SNIPPET],
                detail={"comment": message.feedback_comment} if kind == "feedback" else {},
                reviewed_at=message.reviewed_at,
            )
        )
    return items


async def _guardrail_items(
    session: AsyncSession, include_reviewed: bool, limit: int
) -> list[ReviewItem]:
    query = (
        select(GuardrailEvent, User)
        .join(User, User.id == GuardrailEvent.user_id)
        .order_by(GuardrailEvent.created_at.desc())
    )
    if not include_reviewed:
        query = query.where(GuardrailEvent.reviewed_at.is_(None))
    items = []
    for event, owner in (await session.execute(query.limit(limit))).all():
        message = await session.get(Message, event.message_id) if event.message_id else None
        question = await _question_for(session, message) if message else None
        items.append(
            ReviewItem(
                kind="guardrail",
                id=event.id,
                created_at=event.created_at,
                user_id=owner.id,
                username=owner.username,
                message_id=event.message_id,
                question=question[:SNIPPET] if question else None,
                answer=message.content[:SNIPPET] if message else None,
                detail={
                    "check": event.check,
                    "category": event.category,
                    "action": event.action,
                    "strike": event.strike,
                },
                reviewed_at=event.reviewed_at,
            )
        )
    return items


async def list_queue(
    session: AsyncSession,
    actor: User,
    *,
    kind: Kind | None = None,
    include_reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[ReviewItem]:
    wanted = [kind] if kind else list(KINDS)
    items: list[ReviewItem] = []
    for k in wanted:
        if k == "guardrail":
            items += await _guardrail_items(session, include_reviewed, limit + offset)
        else:
            items += await _message_items(session, k, include_reviewed, limit + offset)
    items.sort(key=lambda i: i.created_at, reverse=True)
    page = items[offset : offset + limit]
    await audit.record(
        session,
        action="review.queue_viewed",
        actor=actor,
        target_type="review_queue",
        detail={
            "kind": kind,
            "include_reviewed": include_reviewed,
            "offset": offset,
            # Whose content the admin saw (spec §6.6).
            "items": [
                {
                    "kind": i.kind,
                    "id": str(i.id),
                    "message_id": str(i.message_id) if i.message_id else None,
                    "user_id": str(i.user_id),
                }
                for i in page
            ],
        },
    )
    return page


async def _assistant_message(session: AsyncSession, message_id: uuid.UUID) -> Message:
    message = await session.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise evaluation.NotFound("Message not found")
    return message


def _matches_kind(message: Message, kind: Kind) -> bool:
    if message.role != "assistant":
        return False
    if kind == "feedback":
        return message.feedback_rating == -1
    return bool(message.low_confidence)


async def mark_reviewed(session: AsyncSession, actor: User, kind: Kind, item_id: uuid.UUID) -> None:
    target: Message | GuardrailEvent | None
    if kind == "guardrail":
        target = await session.get(GuardrailEvent, item_id)
    else:
        # One reviewed_at per message: an answer reviewed for one reason counts as reviewed for
        # both (the audit row records which kind was clicked).
        target = await session.get(Message, item_id)
        if target is not None and not _matches_kind(target, kind):
            target = None
    if target is None:
        raise evaluation.NotFound("Review item not found")
    target.reviewed_at = datetime.now(UTC)
    target.reviewed_by = actor.id
    await session.flush()
    await audit.record(
        session,
        action="review.marked_reviewed",
        actor=actor,
        target_type=kind,
        target_id=item_id,
    )


async def message_detail(
    session: AsyncSession, actor: User, message_id: uuid.UUID
) -> MessageReview:
    message = await _assistant_message(session, message_id)
    conversation = await session.get(Conversation, message.conversation_id)
    assert conversation is not None
    owner = await session.get(User, conversation.user_id)
    assert owner is not None
    await audit.record(
        session,
        action="review.message_viewed",
        actor=actor,
        target_type="message",
        target_id=message.id,
        detail={"owner_id": str(owner.id), "conversation_id": str(conversation.id)},
    )
    return MessageReview(
        conversation_id=conversation.id,
        user=ReviewUser(id=owner.id, username=owner.username),
        question=await _question_for(session, message),
        answer=ReviewAnswer.model_validate(message),
    )


async def add_message_to_set(
    session: AsyncSession, actor: User, message_id: uuid.UUID, data: AddToSetIn
) -> EvalCase:
    message = await _assistant_message(session, message_id)
    question = await _question_for(session, message)
    conversation = await session.get(Conversation, message.conversation_id)
    owner = await session.get(User, conversation.user_id) if conversation else None
    if question is None or owner is None:
        raise evaluation.InvalidCase("This answer has no question to evaluate")
    if not owner.groups:
        raise evaluation.InvalidCase("The user who asked this has no groups to run as")
    eval_set = await evaluation.get_set(session, data.eval_set_id)
    case = await evaluation.add_case(
        session,
        eval_set,
        CaseIn(
            question=question,
            expected_answer=data.expected_answer,
            collection_ids=[uuid.UUID(c) for c in message.collection_ids],
            run_as_group_ids=[g.id for g in owner.groups],
            unanswerable=data.unanswerable,
        ),
        origin="review",
        source_message_id=message.id,
    )
    await audit.record(
        session,
        action="review.added_to_eval_set",
        actor=actor,
        target_type="message",
        target_id=message.id,
        detail={"eval_set_id": str(eval_set.id), "case_id": str(case.id)},
    )
    return case
