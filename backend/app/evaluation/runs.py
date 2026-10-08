"""Eval runs: create (queued), execute in the worker, summarize, compare (spec §7.1)."""

import asyncio
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import service as audit
from app.chat.answer import ChatDeps
from app.evaluation import service
from app.evaluation.models import EvalCase, EvalResult, EvalRun
from app.evaluation.runner import deterministic_metrics, run_case
from app.evaluation.scoring import METRICS, ScoreInput, Scorer
from app.llm.models import RagConfigVersion
from app.llm.rag_config import RagConfig, get_active
from app.users.models import Group, User

logger = logging.getLogger(__name__)
REGRESSION_DROP = 0.1
RUN_TIMEOUT = timedelta(hours=6)
TIMED_OUT = "Timed out: the evaluation worker stopped"
# Per-case 0/1 metrics averaged into a summary rate: "I don't know" accuracy on unanswerable
# cases, and the share of answerable cases that got a cited answer. Both feed the score.
RATES = {"idk_accuracy": "idk_correct", "answered_rate": "answered"}


async def reap_stale_runs(session: AsyncSession, now: datetime | None = None) -> int:
    """Fail runs stuck in `running` past RUN_TIMEOUT. Runs are acked early, so a worker that
    died mid-run would otherwise leave them running forever. Flushes; the caller commits."""
    now = now or datetime.now(UTC)
    result = await session.execute(
        update(EvalRun)
        .where(EvalRun.status == "running", EvalRun.started_at < now - RUN_TIMEOUT)
        .values(status="failed", error=TIMED_OUT, finished_at=now)
    )
    return result.rowcount or 0


async def create_run(
    session: AsyncSession,
    actor: User,
    eval_set_id: uuid.UUID,
    rag_config_id: uuid.UUID | None = None,
) -> EvalRun:
    eval_set = await service.get_set(session, eval_set_id)
    cases = await service.list_cases(session, eval_set.id)
    if not cases:
        raise service.InvalidCase("This eval set has no cases")
    if rag_config_id is not None:
        row = await session.get(RagConfigVersion, rag_config_id)
        if row is None:
            raise service.NotFound("RAG config version not found")
        version, config = row.version, RagConfig.model_validate(row.data)
    else:
        version, config = await get_active(session)
        row = (
            await session.scalar(
                select(RagConfigVersion).where(RagConfigVersion.version == version)
            )
            if version is not None
            else None
        )
    run = EvalRun(
        eval_set_id=eval_set.id,
        rag_config_id=row.id if row is not None else None,
        rag_config_version=version,
        config=config.model_dump(mode="json"),
        case_count=len(cases),
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session,
        action="eval_run.created",
        actor=actor,
        target_type="eval_run",
        target_id=run.id,
        detail={"eval_set_id": str(eval_set.id), "rag_config_version": version},
    )
    return run


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return int(ordered[index])


def _rate(results: Sequence[EvalResult], metric: str) -> float | None:
    values = [r.metrics.get(metric) for r in results if r.metrics.get(metric) is not None]
    return round(mean(float(v) for v in values), 4) if values else None


def summarize(results: Sequence[EvalResult]) -> dict[str, Any]:
    metric_means: dict[str, float] = {}
    for name in METRICS:
        values = [r.metrics.get(name) for r in results if r.metrics.get(name) is not None]
        if values:
            metric_means[name] = round(mean(float(v) for v in values), 4)
    rates = {key: _rate(results, metric) for key, metric in RATES.items()}
    parts = list(metric_means.values()) + [v for v in rates.values() if v is not None]
    outcomes: dict[str, int] = {}
    for r in results:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    latencies = [r.latency_ms for r in results]
    return {
        "cases": len(results),
        "errors": outcomes.get("error", 0),
        "outcomes": outcomes,
        "metrics": metric_means,
        **rates,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cost_per_question_usd": round(mean(r.cost_usd for r in results), 6) if results else 0.0,
        "score": round(mean(parts), 4) if parts else None,
    }


async def _load(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> tuple[EvalRun, list[EvalCase], dict[str, Group]] | None:
    """Claim a queued run (queued -> running, atomically) and load what it needs. Returns None
    when the run is gone or already claimed, so a redelivered task never runs it twice."""
    async with sessionmaker() as session:
        claimed = await session.scalar(
            update(EvalRun)
            .where(EvalRun.id == run_id, EvalRun.status == "queued")
            .values(status="running", started_at=datetime.now(UTC), error=None)
            .returning(EvalRun.id)
        )
        if claimed is None:
            logger.warning(
                "Eval run %s is not queued (missing or already claimed); skipping", run_id
            )
            return None
        run = await session.get(EvalRun, run_id)
        assert run is not None
        cases = list(
            (
                await session.scalars(
                    select(EvalCase)
                    .where(EvalCase.eval_set_id == run.eval_set_id)
                    .order_by(EvalCase.seq)
                )
            ).all()
        )
        group_ids = {uuid.UUID(g) for c in cases for g in c.run_as_group_ids}
        groups = (
            (await session.scalars(select(Group).where(Group.id.in_(group_ids)))).all()
            if group_ids
            else []
        )
        await session.execute(delete(EvalResult).where(EvalResult.run_id == run_id))
        await session.commit()
        return run, cases, {str(g.id): g for g in groups}


async def _fail(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, exc: Exception
) -> None:
    logger.error("Eval run %s failed", run_id, exc_info=exc)
    async with sessionmaker() as session:
        stored = await session.get(EvalRun, run_id)
        if stored is not None:
            stored.status, stored.finished_at = "failed", datetime.now(UTC)
            stored.error = f"{type(exc).__name__}: {exc}"[:1000]
            await session.commit()


async def execute_run(
    run_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    scorer_factory: Callable[[str], Scorer],
    concurrency: int = 4,
) -> None:
    """Run every case of the run's eval set and store results and a summary. A case that fails
    is recorded as an error; only an infrastructure failure marks the whole run failed. A run
    that is not queued (already running, finished or gone) is skipped."""
    try:
        loaded = await _load(sessionmaker, run_id)
    except Exception as exc:
        await _fail(sessionmaker, run_id, exc)
        return
    if loaded is None:
        return
    run, cases, groups = loaded
    try:
        config = RagConfig.model_validate(run.config)
        scorer = scorer_factory(config.eval_judge_model)
        limit = asyncio.Semaphore(concurrency)

        async def one(case: EvalCase) -> None:
            async with limit:
                case_groups = [groups[g] for g in case.run_as_group_ids if g in groups]
                outcome = await run_case(
                    sessionmaker, deps, config, case, case_groups, run_id=run.id
                )
                metrics: dict[str, Any] = deterministic_metrics(case, outcome)
                if outcome.outcome != "error":
                    metrics |= await scorer.score(
                        ScoreInput(
                            question=case.question,
                            answer=outcome.answer,
                            contexts=outcome.contexts,
                            reference=case.expected_answer,
                            answered=outcome.outcome == "answered",
                        )
                    )
                async with sessionmaker() as session:
                    session.add(
                        EvalResult(
                            run_id=run.id,
                            case_id=case.id,
                            case_seq=case.seq,
                            question=case.question,
                            unanswerable=case.unanswerable,
                            outcome=outcome.outcome,
                            answer=outcome.answer,
                            sources=outcome.sources,
                            metrics=metrics,
                            latency_ms=outcome.latency_ms,
                            cost_usd=outcome.cost_usd,
                            trace_id=outcome.trace_id,
                            error=outcome.error,
                        )
                    )
                    await session.commit()

        await asyncio.gather(*(one(case) for case in cases))
        async with sessionmaker() as session:
            stored = await session.get(EvalRun, run.id)
            assert stored is not None
            results = (
                await session.scalars(select(EvalResult).where(EvalResult.run_id == run.id))
            ).all()
            stored.summary = summarize(results)
            stored.status, stored.finished_at = "completed", datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        await _fail(sessionmaker, run_id, exc)


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> tuple[EvalRun, list[EvalResult]]:
    run = await session.get(EvalRun, run_id, populate_existing=True)  # workers write elsewhere
    if run is None:
        raise service.NotFound("Eval run not found")
    results = (
        await session.scalars(
            select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.case_seq)
        )
    ).all()
    return run, list(results)


async def list_runs(session: AsyncSession, eval_set_id: uuid.UUID | None = None) -> list[EvalRun]:
    query = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(200)
    if eval_set_id is not None:
        query = query.where(EvalRun.eval_set_id == eval_set_id)
    return list((await session.scalars(query)).all())


def _regression(a: EvalResult, b: EvalResult) -> list[str]:
    reasons = []
    if b.outcome == "error" and a.outcome != "error":
        reasons.append("now errors")
    if a.outcome == "answered" and b.outcome != "answered":
        reasons.append(f"outcome answered → {b.outcome}")
    for name in (*METRICS, *RATES.values()):
        before, after = a.metrics.get(name), b.metrics.get(name)
        if before is not None and after is not None and before - after >= REGRESSION_DROP:
            reasons.append(f"{name} {before:.2f} → {after:.2f}")
    return reasons


async def compare(session: AsyncSession, a_id: uuid.UUID, b_id: uuid.UUID) -> dict[str, Any]:
    run_a, results_a = await get_run(session, a_id)
    run_b, results_b = await get_run(session, b_id)
    by_case_b = {r.case_id: r for r in results_b if r.case_id is not None}
    questions = []
    for a in results_a:
        b = by_case_b.get(a.case_id) if a.case_id is not None else None
        if b is None:
            continue
        reasons = _regression(a, b)
        questions.append(
            {
                "case_id": str(a.case_id),
                "question": a.question,
                "a": {"outcome": a.outcome, "metrics": a.metrics, "answer": a.answer},
                "b": {"outcome": b.outcome, "metrics": b.metrics, "answer": b.answer},
                "regressed": bool(reasons),
                "reasons": reasons,
            }
        )
    keys = set(run_a.summary.get("metrics", {})) | set(run_b.summary.get("metrics", {}))
    deltas = {
        k: round(run_b.summary["metrics"][k] - run_a.summary["metrics"][k], 4)
        for k in keys
        if k in run_a.summary.get("metrics", {}) and k in run_b.summary.get("metrics", {})
    }
    for k in (*RATES, "score", "latency_p95_ms", "cost_per_question_usd"):
        if run_a.summary.get(k) is not None and run_b.summary.get(k) is not None:
            deltas[k] = round(run_b.summary[k] - run_a.summary[k], 6)
    return {
        "a": {"id": str(run_a.id), "summary": run_a.summary},
        "b": {"id": str(run_b.id), "summary": run_b.summary},
        "deltas": deltas,
        "questions": questions,
    }


async def latest_scores(
    session: AsyncSession, rag_config_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Latest completed eval run per config version (spec §7.1 activation warning)."""
    if not rag_config_ids:
        return {}
    query = (
        select(EvalRun)
        .where(EvalRun.rag_config_id.in_(rag_config_ids), EvalRun.status == "completed")
        .order_by(EvalRun.finished_at.desc())
    )
    latest: dict[uuid.UUID, dict[str, Any]] = {}
    for run in (await session.scalars(query)).all():
        if run.rag_config_id is not None and run.rag_config_id not in latest:
            latest[run.rag_config_id] = {
                "run_id": str(run.id),
                "eval_set_id": str(run.eval_set_id),
                "score": run.summary.get("score"),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
    return latest
