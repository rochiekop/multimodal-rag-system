"""Answering one question: rewrite → retrieve → confidence check → stream → cite → log.

Yields ChatEvents; the API turns them into Server-Sent Events. DB sessions are short so no
connection is held while the model streams."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.citations import clean_citations, format_sources, source_card
from app.chat.models import Conversation, Message
from app.core.tracing import answer_span
from app.llm.gateway import content_text
from app.llm.rag_config import RagConfig, compute_cost, get_active
from app.retrieval.search import RetrievalDeps, RetrievedChunk, retrieve
from app.users.models import User

logger = logging.getLogger(__name__)
ERROR_MESSAGE = "Something went wrong while answering. Please try again."
CLOSEST_MATCHES = 3


@dataclass
class ChatDeps:
    retrieval: RetrievalDeps
    chat_model: Callable[[str], BaseChatModel]  # model name -> LangChain chat model


@dataclass(frozen=True)
class ChatEvent:
    event: str  # meta | sources | token | done | error
    data: dict[str, Any]


@dataclass
class _Usage:
    tokens: dict[str, list[int]] = field(default_factory=dict)  # model -> [input, output]

    def add(self, model: str, usage: Any) -> None:
        if not usage:
            return
        entry = self.tokens.setdefault(model, [0, 0])
        entry[0] += int(usage.get("input_tokens", 0))
        entry[1] += int(usage.get("output_tokens", 0))


async def _history(session: AsyncSession, conversation_id: uuid.UUID, turns: int) -> list[Message]:
    if turns == 0:
        return []
    query = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id, Message.outcome.is_distinct_from("error")
        )
        .order_by(Message.seq.desc())
        .limit(turns * 2)
    )
    return list(reversed((await session.scalars(query)).all()))


async def _rewrite(
    deps: ChatDeps, config: RagConfig, history: list[Message], question: str, usage: _Usage
) -> str:
    transcript = "\n".join(f"{m.role}: {m.content}" for m in history)
    response = await deps.chat_model(config.rewrite_model).ainvoke(
        [
            SystemMessage(config.rewrite_prompt),
            HumanMessage(f"Conversation:\n{transcript}\n\nFollow-up question: {question}"),
        ]
    )
    usage.add(config.rewrite_model, getattr(response, "usage_metadata", None))
    return content_text(response.content).strip() or question


async def _generate(
    deps: ChatDeps, config: RagConfig, chunks: list[RetrievedChunk], question: str, usage: _Usage
) -> AsyncIterator[str]:
    messages = [
        SystemMessage(config.system_prompt),
        HumanMessage(f"Sources:\n\n{format_sources(chunks)}\n\nQuestion: {question}"),
    ]
    async for chunk in deps.chat_model(config.chat_model).astream(messages):
        usage.add(config.chat_model, getattr(chunk, "usage_metadata", None))
        text = content_text(chunk.content)
        if text:
            yield text


async def answer(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    *,
    user: User,
    conversation_id: uuid.UUID,
    question: str,
    collection_ids: Sequence[uuid.UUID] = (),
) -> AsyncIterator[ChatEvent]:
    """The caller has already checked that the conversation belongs to the user."""
    started = time.monotonic()
    async with sessionmaker() as session:
        config_version, config = await get_active(session)
        history = await _history(session, conversation_id, config.history_turns)
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=question,
            collection_ids=[str(c) for c in collection_ids],
        )
        session.add(user_message)
        await session.commit()
    yield ChatEvent(
        "meta",
        {"conversation_id": str(conversation_id), "user_message_id": str(user_message.id)},
    )

    usage = _Usage()
    standalone = question
    sources: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    top_score: float | None = None
    with answer_span("chat.answer") as trace_id:
        try:
            if history:
                standalone = await _rewrite(deps, config, history, question, usage)
            async with sessionmaker() as session:
                chunks = await retrieve(
                    session,
                    deps.retrieval,
                    user=user,
                    question=standalone,
                    collection_ids=collection_ids,
                    config=config,
                )
            cards = [source_card(n, c) for n, c in enumerate(chunks, start=1)]
            top_score = chunks[0].score if chunks else None
            if top_score is None or top_score < config.rerank_threshold:
                outcome, content = "not_found", config.not_found_message
                sources = cards[:CLOSEST_MATCHES]
                yield ChatEvent("sources", {"sources": sources})
            else:
                sources = cards
                yield ChatEvent("sources", {"sources": sources})
                parts: list[str] = []
                async for delta in _generate(deps, config, chunks, standalone, usage):
                    parts.append(delta)
                    yield ChatEvent("token", {"text": delta})
                content, used = clean_citations("".join(parts), len(chunks))
                citations = [cards[n - 1] for n in used]
                outcome = "answered"
        except Exception:
            logger.exception("Answer failed for conversation %s", conversation_id)
            outcome, content, citations = "error", ERROR_MESSAGE, []

        async with sessionmaker() as session:
            message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                standalone_question=standalone if standalone != question else None,
                collection_ids=[str(c) for c in collection_ids],
                sources=sources,
                citations=citations,
                outcome=outcome,
                top_score=top_score,
                latency_ms=int((time.monotonic() - started) * 1000),
                input_tokens=sum(t[0] for t in usage.tokens.values()),
                output_tokens=sum(t[1] for t in usage.tokens.values()),
                cost_usd=compute_cost(config, usage.tokens),
                trace_id=trace_id,
                rag_config_version=config_version,
            )
            session.add(message)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(updated_at=func.now())
            )
            await session.commit()

    if outcome == "error":
        yield ChatEvent(
            "error",
            {"code": "answer_failed", "message": ERROR_MESSAGE, "message_id": str(message.id)},
        )
    else:
        yield ChatEvent(
            "done",
            {
                "message_id": str(message.id),
                "content": content,
                "outcome": outcome,
                "citations": citations,
                "trace_id": trace_id,
            },
        )
