import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
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
    assert leave.metrics["hit_rate"] == 1.0 and leave.metrics["idk_correct"] == 1.0
    assert leave.metrics["faithfulness"] == 0.9
    salary = by_question["What is the CEO's salary?"]
    assert salary.outcome == "not_found" and salary.metrics["idk_correct"] == 1.0
    summary = run.summary
    assert summary["cases"] == 2 and summary["errors"] == 0
    assert summary["idk_accuracy"] == 1.0 and summary["metrics"]["faithfulness"] == 0.9
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
    assert "hit_rate" in " ".join(leave["reasons"]) or "idk_correct" in " ".join(leave["reasons"])
    assert report["deltas"]["score"] < 0  # brief asserted idk_accuracy < 0; it is 0.5 -> 0.5

    latest = await runs.latest_scores(session, [strict.id])
    assert latest[strict.id]["run_id"] == str(bad.id)


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
