"""Conversations and feedback. Users only ever reach their own conversations; anything else
is reported as not found. Functions flush but never commit; callers commit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation, Message
from app.users.models import User

TITLE_CHARS = 80
LIST_LIMIT = 200


class ChatServiceError(Exception):
    code = "chat_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ChatServiceError):
    code = "not_found"


def _title(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def get_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFound("Conversation not found")
    return conversation


async def start_or_get_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID | None, question: str
) -> Conversation:
    if conversation_id is not None:
        return await get_conversation(session, user, conversation_id)
    conversation = Conversation(user_id=user.id, title=_title(question))
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations(
    session: AsyncSession, user: User, search: str | None = None
) -> list[Conversation]:
    query = select(Conversation).where(Conversation.user_id == user.id)
    if search:
        pattern = _like(search)
        in_messages = (
            select(Message.id)
            .where(
                Message.conversation_id == Conversation.id,
                Message.content.ilike(pattern, escape="\\"),
            )
            .exists()
        )
        query = query.where(or_(Conversation.title.ilike(pattern, escape="\\"), in_messages))
    query = query.order_by(Conversation.updated_at.desc()).limit(LIST_LIMIT)
    return list((await session.scalars(query)).all())


async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    query = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    return list((await session.scalars(query)).all())


async def rename_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID, title: str
) -> Conversation:
    conversation = await get_conversation(session, user, conversation_id)
    conversation.title = title.strip() or conversation.title
    await session.flush()
    return conversation


async def delete_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(session, user, conversation_id)
    await session.delete(conversation)  # messages go with it (ON DELETE CASCADE)
    await session.flush()


async def set_feedback(
    session: AsyncSession, user: User, message_id: uuid.UUID, rating: int, comment: str | None
) -> Message:
    message = await session.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise NotFound("Message not found")
    try:
        await get_conversation(session, user, message.conversation_id)
    except NotFound:
        raise NotFound("Message not found") from None
    message.feedback_rating = rating
    message.feedback_comment = comment
    message.feedback_at = datetime.now(UTC)
    await session.flush()
    return message
