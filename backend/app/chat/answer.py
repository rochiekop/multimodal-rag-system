"""Answering one question: input guardrails → rewrite → retrieve → confidence check →
stream through output guardrails → cite → groundedness → log.

Yields ChatEvents; the API turns them into Server-Sent Events. DB sessions are short, so no
connection is held while the model streams. The assistant message, its usage record and its
guardrail events are saved in a shielded `finally`, so a client that disconnects mid-answer
still gets its answer recorded (outcome "cancelled") and metered."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.citations import clean_citations, format_sources, source_card
from app.chat.models import Conversation, Message
from app.core.tracing import answer_span
from app.guardrails import service as guardrails
from app.guardrails.input import InputDecision, check_input
from app.guardrails.models import UsageRecord
from app.guardrails.output import OutputGuard, SystemPromptLeak, judge_groundedness
from app.llm.gateway import content_text
from app.llm.rag_config import RagConfig, compute_cost, get_active
from app.retrieval.access import visible_collections
from app.retrieval.search import RetrievalDeps, RetrievedChunk, retrieve
from app.users.models import User

logger = logging.getLogger(__name__)
ERROR_MESSAGE = "Something went wrong while answering. Please try again."
CLOSEST_MATCHES = 3
_DECISION_OUTCOME = {"block": "blocked", "support": "support", "off_topic": "off_topic"}
_EVENT_ACTION = {"block": "blocked", "support": "support", "off_topic": "redirected"}


@dataclass
class ChatDeps:
    retrieval: RetrievalDeps
    chat_model: Callable[[str], BaseChatModel]  # model name -> LangChain chat model
    moderate: Callable[[str], Awaitable[dict[str, bool]]]  # provider moderation flags


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


@dataclass
class _Result:
    """What the answer became. Starts as "cancelled" so an interrupted answer is saved as such."""

    standalone: str
    outcome: str = "cancelled"
    content: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    top_score: float | None = None
    low_confidence: bool = False
    decision: InputDecision | None = None  # the check that stopped the answer, if any
    flags: list[tuple[str, str | None]] = field(default_factory=list)


async def _history(session: AsyncSession, conversation_id: uuid.UUID, turns: int) -> list[Message]:
    if turns == 0:
        return []
    query = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.outcome.is_distinct_from("error"),
        )
        .order_by(Message.seq.desc())
        .limit(turns * 2)
    )
    return list(reversed((await session.scalars(query)).all()))


def _model(deps: ChatDeps, config: RagConfig, name: str) -> Runnable:
    """The named model, falling back to RagConfig.fallback_model on failure (spec §5.3)."""
    primary = deps.chat_model(name)
    fallback = config.fallback_model
    if fallback and fallback != name:
        return primary.with_fallbacks([deps.chat_model(fallback)])
    return primary


async def _rewrite(
    deps: ChatDeps, config: RagConfig, history: list[Message], question: str, usage: _Usage
) -> str:
    transcript = "\n".join(f"{m.role}: {m.content}" for m in history)
    response = await _model(deps, config, config.rewrite_model).ainvoke(
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
    async for chunk in _model(deps, config, config.chat_model).astream(messages):
        usage.add(config.chat_model, getattr(chunk, "usage_metadata", None))
        text = content_text(chunk.content)
        if text:
            yield text


async def _run(
    deps: ChatDeps,
    sessionmaker: async_sessionmaker[AsyncSession],
    config: RagConfig,
    *,
    user: User,
    question: str,
    collection_ids: Sequence[uuid.UUID],
    history: list[Message],
    sensitive_scope: bool,
    usage: _Usage,
    result: _Result,
) -> AsyncIterator[ChatEvent]:
    settings = config.guardrails
    decision = await check_input(
        settings,
        question,
        moderate=deps.moderate,
        chat_model=deps.chat_model,
        sensitive_scope=sensitive_scope,
        on_usage=usage.add,
    )
    result.flags.extend(decision.flags)
    if decision.action != "allow":
        result.decision = decision
        result.outcome = _DECISION_OUTCOME[decision.action]
        result.content = {
            "block": settings.blocked_message,
            "support": settings.support_message,
            "off_topic": settings.off_topic_message,
        }[decision.action]
        return

    if history:
        result.standalone = await _rewrite(deps, config, history, question, usage)
    async with sessionmaker() as session:
        chunks = await retrieve(
            session,
            deps.retrieval,
            user=user,
            question=result.standalone,
            collection_ids=collection_ids,
            config=config,
        )
    cards = [source_card(n, c) for n, c in enumerate(chunks, start=1)]
    result.top_score = chunks[0].score if chunks else None
    if result.top_score is None or result.top_score < config.rerank_threshold:
        result.sources = cards[:CLOSEST_MATCHES]
        yield ChatEvent("sources", {"sources": result.sources})
        result.outcome, result.content = "not_found", config.not_found_message
        return

    result.sources = cards
    yield ChatEvent("sources", {"sources": cards})
    guard = OutputGuard(
        settings,
        sources_text="\n".join(c.text for c in chunks),
        system_prompt=config.system_prompt,
    )
    try:
        async for delta in _generate(deps, config, chunks, result.standalone, usage):
            safe = guard.feed(delta)
            result.content = guard.text
            if safe:
                yield ChatEvent("token", {"text": safe})
        tail = guard.finish()
        result.content = guard.text
        if tail:
            yield ChatEvent("token", {"text": tail})
    except SystemPromptLeak:
        result.decision = InputDecision("block", check="system_prompt_leak")
        result.outcome, result.content = "blocked", settings.blocked_message
        return
    result.flags.extend(("pii", name) for name in guard.redactions)

    content, used = clean_citations(guard.text, len(chunks))
    result.content = content
    result.citations = [cards[n - 1] for n in used]
    if settings.groundedness_check:
        verdict = await judge_groundedness(
            deps.chat_model, settings.judge_model, content, format_sources(chunks), usage.add
        )
        if not verdict.grounded:
            result.low_confidence = True
            result.flags.append(("groundedness", None))
    result.outcome = "answered"


def _guardrail_detail(result: _Result) -> dict[str, Any] | None:
    flags = [{"check": c, "category": k} for c, k in dict.fromkeys(result.flags)]
    if result.decision is None and not flags:
        return None
    detail: dict[str, Any] = {"flags": flags}
    if result.decision is not None:
        detail.update(check=result.decision.check, category=result.decision.category)
    return detail


async def _save(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user: User,
    conversation_id: uuid.UUID,
    question: str,
    collection_ids: Sequence[uuid.UUID],
    config: RagConfig,
    config_version: int | None,
    usage: _Usage,
    result: _Result,
    trace_id: str | None,
    started: float,
) -> tuple[Message, guardrails.StrikeResult | None]:
    settings = config.guardrails
    async with sessionmaker() as session:
        input_tokens = sum(t[0] for t in usage.tokens.values())
        output_tokens = sum(t[1] for t in usage.tokens.values())
        cost = compute_cost(config, usage.tokens)
        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=result.content,
            standalone_question=result.standalone if result.standalone != question else None,
            collection_ids=[str(c) for c in collection_ids],
            sources=result.sources,
            citations=result.citations,
            outcome=result.outcome,
            low_confidence=result.low_confidence,
            guardrail=_guardrail_detail(result),
            top_score=result.top_score,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            trace_id=trace_id,
            rag_config_version=config_version,
        )
        session.add(message)
        await session.flush()
        session.add(
            UsageRecord(
                user_id=user.id,
                message_id=message.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        )
        strike: guardrails.StrikeResult | None = None
        decision = result.decision
        if decision is not None and decision.check is not None:
            strike = await guardrails.record_event(
                session,
                user=user,
                check=decision.check,
                category=decision.category,
                action=_EVENT_ACTION[decision.action],
                strike=decision.strike,
                conversation_id=conversation_id,
                message_id=message.id,
                settings=settings,
            )
        for check, category in dict.fromkeys(result.flags):
            await guardrails.record_event(
                session,
                user=user,
                check=check,
                category=category,
                action="flagged",
                conversation_id=conversation_id,
                message_id=message.id,
                settings=settings,
            )
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await session.commit()
    return message, strike if decision is not None and decision.strike else None


async def answer(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    *,
    user: User,
    conversation_id: uuid.UUID,
    question: str,
    collection_ids: Sequence[uuid.UUID] = (),
) -> AsyncIterator[ChatEvent]:
    """The caller has already checked ownership and the pre-flight limits."""
    started = time.monotonic()
    async with sessionmaker() as session:
        config_version, config = await get_active(session)
        history = await _history(session, conversation_id, config.history_turns)
        visible = await visible_collections(session, user)
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=question,
            collection_ids=[str(c) for c in collection_ids],
        )
        session.add(user_message)
        await session.commit()
    wanted = set(collection_ids)
    sensitive_scope = any(c.sensitive for c in visible if not wanted or c.id in wanted)
    yield ChatEvent(
        "meta",
        {"conversation_id": str(conversation_id), "user_message_id": str(user_message.id)},
    )

    usage = _Usage()
    result = _Result(standalone=question)
    with answer_span("chat.answer") as trace_id:
        try:
            async for event in _run(
                deps,
                sessionmaker,
                config,
                user=user,
                question=question,
                collection_ids=collection_ids,
                history=history,
                sensitive_scope=sensitive_scope,
                usage=usage,
                result=result,
            ):
                yield event
        except Exception:
            logger.exception("Answer failed for conversation %s", conversation_id)
            result.outcome, result.content, result.citations = "error", ERROR_MESSAGE, []
        finally:
            # Runs on success, error and client disconnect alike; shielded so a cancelled
            # request still records the answer and its usage.
            with anyio.CancelScope(shield=True):
                message, strike = await _save(
                    sessionmaker,
                    user=user,
                    conversation_id=conversation_id,
                    question=question,
                    collection_ids=collection_ids,
                    config=config,
                    config_version=config_version,
                    usage=usage,
                    result=result,
                    trace_id=trace_id,
                    started=started,
                )

    if result.outcome == "error":
        yield ChatEvent(
            "error",
            {"code": "answer_failed", "message": ERROR_MESSAGE, "message_id": str(message.id)},
        )
        return
    done: dict[str, Any] = {
        "message_id": str(message.id),
        "content": result.content,
        "outcome": result.outcome,
        "citations": result.citations,
        "low_confidence": result.low_confidence,
        "trace_id": trace_id,
    }
    if strike is not None:
        done.update(
            strikes=strike.strikes,
            strike_limit=config.guardrails.strike_limit,
            locked_until=strike.locked_until.isoformat() if strike.locked_until else None,
        )
    yield ChatEvent("done", done)
