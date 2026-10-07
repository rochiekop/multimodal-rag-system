"""User-facing chat API: collection picker, streamed answers (SSE), conversation history,
feedback and the page images the source viewer shows."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.errors import api_error
from app.auth.deps import CurrentUser, SessionDep
from app.chat import service
from app.chat.answer import ERROR_MESSAGE, ChatDeps, ChatEvent, answer
from app.chat.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationOut,
    ConversationRename,
    FeedbackIn,
    MessageOut,
    VisibleCollectionOut,
)
from app.core.storage import FileStore
from app.documents.service import page_key
from app.retrieval.access import permitted_documents, visible_collections

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _http_error(exc: service.ChatServiceError) -> HTTPException:
    return api_error(404 if isinstance(exc, service.NotFound) else 400, exc.code, exc.message)


def _sse(event: ChatEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.get("/collections")
async def list_collections(user: CurrentUser, session: SessionDep) -> list[VisibleCollectionOut]:
    return [
        VisibleCollectionOut.model_validate(c) for c in await visible_collections(session, user)
    ]


@router.post("/chat")
async def chat(
    body: ChatRequest, user: CurrentUser, session: SessionDep, request: Request
) -> StreamingResponse:
    try:
        conversation = await service.start_or_get_conversation(
            session, user, body.conversation_id, body.question
        )
    except service.ChatServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    deps: ChatDeps = request.app.state.chat_deps
    events = answer(
        request.app.state.sessionmaker,
        deps,
        user=user,
        conversation_id=conversation.id,
        question=body.question,
        collection_ids=body.collection_ids,
    )

    async def stream() -> AsyncIterator[str]:
        try:
            async for event in events:
                yield _sse(event)
        except Exception:
            logger.exception("Answer stream failed")
            yield _sse(ChatEvent("error", {"code": "answer_failed", "message": ERROR_MESSAGE}))

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
async def list_conversations(
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ConversationOut]:
    conversations = await service.list_conversations(session, user, q)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ConversationDetail:
    try:
        conversation = await service.get_conversation(session, user, conversation_id)
    except service.ChatServiceError as exc:
        raise _http_error(exc) from None
    messages = await service.list_messages(session, conversation.id)
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationRename, user: CurrentUser, session: SessionDep
) -> ConversationOut:
    try:
        conversation = await service.rename_conversation(session, user, conversation_id, body.title)
    except service.ChatServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await session.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    try:
        await service.delete_conversation(session, user, conversation_id)
    except service.ChatServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return Response(status_code=204)


@router.post("/messages/{message_id}/feedback")
async def give_feedback(
    message_id: uuid.UUID, body: FeedbackIn, user: CurrentUser, session: SessionDep
) -> MessageOut:
    try:
        message = await service.set_feedback(session, user, message_id, body.rating, body.comment)
    except service.ChatServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return MessageOut.model_validate(message)


@router.get("/documents/{document_id}/pages/{page_no}")
async def page_image(
    document_id: uuid.UUID, page_no: int, user: CurrentUser, session: SessionDep, request: Request
) -> Response:
    """A page of the document's current version, only if the user may read the document."""
    document = (await permitted_documents(session, user, {document_id})).get(document_id)
    store: FileStore = request.app.state.store
    if document is None or document.current_version_id is None or page_no < 1:
        raise api_error(404, "not_found", "Page not found")
    key = page_key(document.current_version_id, page_no)
    if not await asyncio.to_thread(store.exists, key):
        raise api_error(404, "not_found", "Page not found")
    data = await asyncio.to_thread(store.read, key)
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
