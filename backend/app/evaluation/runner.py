"""Runs one eval case through the real pipeline as a transient user with the case's run-as
groups, and computes the metrics that need no judge (hit rate, "I don't know" accuracy)."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.answer import ChatDeps, answer_once
from app.core.tracing import answer_span
from app.evaluation.models import EvalCase
from app.llm.rag_config import RagConfig, compute_cost
from app.users.models import Group, User

logger = logging.getLogger(__name__)


@dataclass
class CaseOutcome:
    outcome: str
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    trace_id: str | None = None
    error: str | None = None


def is_refusal(outcome: str, citations: list[dict[str, Any]]) -> bool:
    """'I don't know': nothing found, or an answer that cites no source."""
    return outcome == "not_found" or (outcome == "answered" and not citations)


def deterministic_metrics(case: EvalCase, outcome: Any) -> dict[str, float | None]:
    hit_rate: float | None = None
    if case.expected_sources:
        found = {(s.get("doc_id"), s.get("page")) for s in outcome.sources}
        found_docs = {doc for doc, _ in found}
        hit = any(
            (e["doc_id"], e["page"]) in found if e.get("page") else e["doc_id"] in found_docs
            for e in case.expected_sources
        )
        hit_rate = 1.0 if hit else 0.0
    idk_correct: float | None = None
    if outcome.outcome != "error":
        idk_correct = (
            1.0 if is_refusal(outcome.outcome, outcome.citations) == case.unanswerable else 0.0
        )
    return {"hit_rate": hit_rate, "idk_correct": idk_correct}


async def run_case(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    config: RagConfig,
    case: EvalCase,
    groups: list[Group],
    *,
    run_id: uuid.UUID,
) -> CaseOutcome:
    # Transient: never added to a session, so nothing about it is stored.
    user = User(id=uuid.uuid4(), username="eval", full_name="Evaluation", role="user")
    user.groups = groups
    started = time.monotonic()
    with answer_span("eval.case") as trace_id:
        span = trace.get_current_span()
        span.set_attribute("eval.run_id", str(run_id))
        span.set_attribute("eval.case_id", str(case.id))
        try:
            result, usage = await answer_once(
                sessionmaker,
                deps,
                config,
                user=user,
                question=case.question,
                collection_ids=[uuid.UUID(c) for c in case.collection_ids or []],
            )
        except Exception as exc:
            logger.exception("Eval case %s failed", case.id)
            return CaseOutcome(
                outcome="error",
                latency_ms=int((time.monotonic() - started) * 1000),
                trace_id=trace_id,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
    return CaseOutcome(
        outcome=result.outcome,
        answer=result.content,
        sources=result.sources,
        citations=result.citations,
        contexts=result.contexts if result.outcome == "answered" else [],
        latency_ms=int((time.monotonic() - started) * 1000),
        cost_usd=compute_cost(config, usage.tokens),
        input_tokens=sum(t[0] for t in usage.tokens.values()),
        output_tokens=sum(t[1] for t in usage.tokens.values()),
        trace_id=trace_id,
    )
