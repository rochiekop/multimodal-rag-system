import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import create_sessionmaker
from app.evaluation import runs
from app.evaluation.models import EvalCase, EvalResult, EvalRun, EvalSet
from app.evaluation.scoring import ScoreInput
from app.ingestion.index import ChunkIndex
from app.llm import rag_config
from app.llm.rag_config import RagConfig
from app.users.models import Role
from tests.factories import (
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
    seed_document,
)


class FakeScorer:
    def __init__(self, value: float = 0.9) -> None:
        self.value = value
        self.items: list[ScoreInput] = []

    async def score(self, item: ScoreInput) -> dict[str, float | None]:
        self.items.append(item)
        return {"faithfulness": self.value} if item.answered else {}


async def _set(session: AsyncSession, index: ChunkIndex) -> tuple[EvalSet, list[EvalCase]]:
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    doc = await seed_document(session, index, coll, ["Annual leave is 25 days per year."])
    eval_set = EvalSet(name="HR")
    session.add(eval_set)
    await session.flush()
    cases = [
        EvalCase(
            eval_set_id=eval_set.id,
            question="How many leave days?",
            expected_answer="25 days",
            expected_sources=[{"doc_id": str(doc.id), "page": 1}],
            run_as_group_ids=[str(hr.id)],
        ),
        EvalCase(
            eval_set_id=eval_set.id,
            question="What is the CEO's salary?",
            unanswerable=True,
            run_as_group_ids=[str(hr.id)],
        ),
    ]
    session.add_all(cases)
    await session.commit()
    return eval_set, cases


async def _execute(engine: AsyncEngine, run: EvalRun, deps, scorer: FakeScorer) -> None:
    await runs.execute_run(
        run.id,
        sessionmaker=create_sessionmaker(engine),
        deps=deps,
        scorer_factory=lambda judge: scorer,
    )


async def test_run_executes_scores_and_summarizes(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()
    assert (run.status, run.case_count, run.rag_config_version) == ("queued", 2, None)

    async def low_for_salary(model: str, query: str, docs: list[str]) -> list[float]:
        return [0.01 if "salary" in query else 0.9 for _ in docs]

    scorer = FakeScorer()
    await _execute(engine, run, chat_deps(chunk_index, rerank=low_for_salary), scorer)
    await session.refresh(run)
    assert run.status == "completed" and run.finished_at is not None
    results = (await session.scalars(select(EvalResult).where(EvalResult.run_id == run.id))).all()
    by_question = {r.question: r for r in results}
    leave = by_question["How many leave days?"]
    assert leave.outcome == "answered"
    assert leave.metrics["hit_rate"] == 1.0 and leave.metrics["answered"] == 1.0
    assert leave.metrics["idk_correct"] is None  # answerable: no "I don't know" score
    assert leave.metrics["faithfulness"] == 0.9
    salary = by_question["What is the CEO's salary?"]
    assert salary.outcome == "not_found" and salary.metrics["idk_correct"] == 1.0
    assert salary.metrics["answered"] is None
    summary = run.summary
    assert summary["cases"] == 2 and summary["errors"] == 0
    assert summary["idk_accuracy"] == 1.0 and summary["answered_rate"] == 1.0
    assert summary["metrics"]["faithfulness"] == 0.9
    assert summary["metrics"]["hit_rate"] == 1.0
    assert summary["latency_p50_ms"] >= 0 and "score" in summary
    # Both non-error cases reach the scorer; only the answered one gets answer metrics.
    assert [i.reference for i in scorer.items if i.answered] == ["25 days"]


async def test_failing_case_is_recorded_and_run_completes(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()

    async def broken_embed(text: str) -> list[float]:
        if "salary" in text:
            raise RuntimeError("embedding service down")
        return [1.0] * 8

    deps = chat_deps(chunk_index)
    deps.retrieval.embed_query = broken_embed
    await _execute(engine, run, deps, FakeScorer())
    await session.refresh(run)
    assert run.status == "completed" and run.summary["errors"] == 1
    failed = await session.scalar(
        select(EvalResult).where(EvalResult.run_id == run.id, EvalResult.outcome == "error")
    )
    assert failed is not None and "embedding service down" in (failed.error or "")


async def test_run_uses_the_chosen_config_and_compare_flags_regressions(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    strict = await rag_config.create_version(session, root, RagConfig(rerank_threshold=0.99))
    await session.commit()

    good = await runs.create_run(session, root, eval_set.id)
    bad = await runs.create_run(session, root, eval_set.id, rag_config_id=strict.id)
    await session.commit()
    assert bad.rag_config_version == strict.version
    for run in (good, bad):
        await _execute(engine, run, chat_deps(chunk_index), FakeScorer())

    report = await runs.compare(session, good.id, bad.id)
    leave = next(q for q in report["questions"] if q["question"] == "How many leave days?")
    assert leave["a"]["outcome"] == "answered" and leave["b"]["outcome"] == "not_found"
    assert leave["regressed"] is True
    assert "outcome answered → not_found" in leave["reasons"]
    assert "answered 1.00 → 0.00" in leave["reasons"]
    assert report["deltas"]["answered_rate"] == -1.0
    assert report["deltas"]["score"] < 0

    latest = await runs.latest_scores(session, [strict.id])
    assert latest[strict.id]["run_id"] == str(bad.id)


async def test_compare_flags_an_answer_that_guardrails_now_block(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    blocking = await rag_config.create_version(
        session,
        root,
        RagConfig.model_validate(
            {
                "guardrails": {
                    "classifier_model": "blocker",
                    "user_daily_cost_usd": 0,
                    "installation_daily_cost_usd": 0,
                }
            }
        ),
    )
    await session.commit()
    good = await runs.create_run(session, root, eval_set.id)
    bad = await runs.create_run(session, root, eval_set.id, rag_config_id=blocking.id)
    await session.commit()
    await _execute(engine, good, chat_deps(chunk_index), FakeScorer())
    verdict = '{"prompt_injection": true, "exfiltration": false, "off_topic": false}'
    blocker = FakeListChatModel(responses=[verdict])
    await _execute(engine, bad, chat_deps(chunk_index, models={"blocker": blocker}), FakeScorer())

    report = await runs.compare(session, good.id, bad.id)
    leave = next(q for q in report["questions"] if q["question"] == "How many leave days?")
    assert (leave["a"]["outcome"], leave["b"]["outcome"]) == ("answered", "blocked")
    assert leave["b"]["metrics"]["answered"] == 0.0
    assert leave["b"]["metrics"]["idk_correct"] is None
    assert leave["regressed"] is True
    assert "outcome answered → blocked" in leave["reasons"]


async def test_a_run_executes_once(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()
    await _execute(engine, run, chat_deps(chunk_index), FakeScorer())
    await session.refresh(run)
    finished_at = run.finished_at

    again = FakeScorer()  # a redelivered task: must not touch the finished run
    await _execute(engine, run, chat_deps(chunk_index), again)
    await session.refresh(run)
    count = select(func.count()).select_from(EvalResult).where(EvalResult.run_id == run.id)
    assert await session.scalar(count) == 2
    assert (run.status, run.finished_at, again.items) == ("completed", finished_at, [])


async def test_a_run_already_running_is_skipped(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    run.status = "running"
    await session.commit()
    scorer = FakeScorer()
    await _execute(engine, run, chat_deps(chunk_index), scorer)
    await session.refresh(run)
    assert (run.status, scorer.items) == ("running", [])
    count = select(func.count()).select_from(EvalResult).where(EvalResult.run_id == run.id)
    assert await session.scalar(count) == 0


async def test_a_run_that_fails_to_load_is_marked_failed(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, cases = await _set(session, chunk_index)
    cases[0].run_as_group_ids = ["not-a-uuid"]
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()
    await _execute(engine, run, chat_deps(chunk_index), FakeScorer())
    await session.refresh(run)
    assert run.status == "failed" and "ValueError" in (run.error or "")


def test_eval_task_is_acked_early() -> None:
    from app.evaluation.tasks import run_eval

    assert run_eval.acks_late is False  # a long run must not be redelivered mid-flight


async def test_runs_api(
    app: FastAPI, client: AsyncClient, session: AsyncSession, enqueued_evals: list[uuid.UUID]
) -> None:
    eval_set, _ = await _set(session, app.state.index)
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    h = bearer(await login(client, "root"))

    created = await client.post(
        "/api/admin/eval-runs", headers=h, json={"eval_set_id": str(eval_set.id)}
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    assert enqueued_evals == [uuid.UUID(run_id)]
    listed = await client.get(
        "/api/admin/eval-runs", headers=h, params={"eval_set_id": str(eval_set.id)}
    )
    assert [r["id"] for r in listed.json()] == [run_id]
    detail = await client.get(f"/api/admin/eval-runs/{run_id}", headers=h)
    assert detail.json()["status"] == "queued" and detail.json()["results"] == []

    empty = EvalSet(name="Empty")
    session.add(empty)
    await session.commit()
    rejected = await client.post(
        "/api/admin/eval-runs", headers=h, json={"eval_set_id": str(empty.id)}
    )
    assert rejected.status_code == 422

    run = await session.get(EvalRun, uuid.UUID(run_id))
    assert run is not None
    run.status, run.summary = "completed", {"score": 0.7}
    await session.commit()
    configs = (await client.get("/api/admin/rag-configs", headers=h)).json()
    assert configs == []  # no versions yet; latest_eval is attached per version when present


async def test_stale_running_runs_are_reaped(session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    eval_set = EvalSet(name="Stale")
    session.add(eval_set)
    await session.flush()
    stale = EvalRun(
        eval_set_id=eval_set.id,
        status="running",
        case_count=1,
        summary={},
        config={},
        started_at=now - timedelta(hours=7),
    )
    fresh = EvalRun(
        eval_set_id=eval_set.id,
        status="running",
        case_count=1,
        summary={},
        config={},
        started_at=now - timedelta(hours=1),
    )
    session.add_all([stale, fresh])
    await session.commit()

    assert await runs.reap_stale_runs(session, now=now) == 1
    await session.commit()
    await session.refresh(stale)
    await session.refresh(fresh)
    assert stale.status == "failed"
    assert stale.error == "Timed out: the evaluation worker stopped"
    assert stale.finished_at == now
    assert fresh.status == "running"
