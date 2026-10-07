import uuid
from types import SimpleNamespace
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.chat.answer import answer_once
from app.chat.models import Conversation, Message
from app.core.config import Settings
from app.core.db import create_sessionmaker
from app.evaluation.models import EvalCase
from app.evaluation.runner import deterministic_metrics, run_case
from app.evaluation.scoring import RagasScorer, ScoreInput, build_ragas_scorer
from app.guardrails.models import GuardrailEvent, UsageRecord
from app.ingestion.index import ChunkIndex
from app.llm.rag_config import RagConfig
from app.users.models import User
from tests.factories import chat_deps, make_collection, make_group, seed_document


async def _world(session: AsyncSession, index: ChunkIndex):
    hr = await make_group(session, "hr")
    eng = await make_group(session, "eng")
    coll = await make_collection(session, "HR", [hr])
    doc = await seed_document(session, index, coll, ["Annual leave is 25 days per year."])
    return hr, eng, coll, doc


async def test_answer_once_saves_nothing(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr, _, _, _ = await _world(session, chunk_index)
    user = User(id=uuid.uuid4(), username="eval", groups=[hr])
    result, usage = await answer_once(
        create_sessionmaker(engine),
        chat_deps(chunk_index),
        RagConfig(),
        user=user,
        question="How many leave days?",
    )
    assert result.outcome == "answered"
    assert result.contexts == ["Annual leave is 25 days per year."]
    assert result.citations and isinstance(usage.tokens, dict)
    for model in (Conversation, Message, UsageRecord, GuardrailEvent):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_run_case_respects_run_as_groups(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr, eng, _, doc = await _world(session, chunk_index)
    case = EvalCase(
        question="How many leave days?",
        expected_sources=[{"doc_id": str(doc.id), "page": 1}],
        run_as_group_ids=[str(eng.id)],
    )
    outsider = await run_case(
        create_sessionmaker(engine),
        chat_deps(chunk_index),
        RagConfig(),
        case,
        [eng],
        run_id=uuid.uuid4(),
    )
    assert outsider.outcome == "not_found" and outsider.contexts == []
    assert deterministic_metrics(case, outsider)["hit_rate"] == 0.0

    insider = await run_case(
        create_sessionmaker(engine),
        chat_deps(chunk_index),
        RagConfig(),
        case,
        [hr],
        run_id=uuid.uuid4(),
    )
    assert insider.outcome == "answered" and insider.error is None
    assert insider.latency_ms >= 0 and insider.answer
    assert deterministic_metrics(case, insider)["hit_rate"] == 1.0


def test_idk_and_answered_metrics() -> None:
    answered = SimpleNamespace(outcome="answered", citations=[{"n": 1}], sources=[])
    uncited = SimpleNamespace(outcome="answered", citations=[], sources=[])
    not_found = SimpleNamespace(outcome="not_found", citations=[], sources=[])
    blocked = SimpleNamespace(outcome="blocked", citations=[], sources=[])

    answerable = EvalCase(question="q", unanswerable=False, expected_sources=[])
    unanswerable = EvalCase(question="q", unanswerable=True, expected_sources=[])
    # "I don't know" accuracy is measured on unanswerable cases only.
    assert deterministic_metrics(answerable, answered) == {
        "hit_rate": None,
        "idk_correct": None,
        "answered": 1.0,
    }
    for outcome in (uncited, not_found, blocked):
        metrics = deterministic_metrics(answerable, outcome)
        assert (metrics["answered"], metrics["idk_correct"]) == (0.0, None)
    assert deterministic_metrics(unanswerable, not_found)["idk_correct"] == 1.0
    assert deterministic_metrics(unanswerable, blocked)["idk_correct"] == 1.0
    assert deterministic_metrics(unanswerable, uncited)["idk_correct"] == 1.0
    assert deterministic_metrics(unanswerable, answered) == {
        "hit_rate": None,
        "idk_correct": 0.0,
        "answered": None,
    }

    errored = SimpleNamespace(outcome="error", citations=[], sources=[])
    with_sources = EvalCase(question="q", unanswerable=False, expected_sources=[{"doc_id": "d"}])
    assert deterministic_metrics(with_sources, errored) == {
        "hit_rate": None,
        "idk_correct": None,
        "answered": None,
    }


async def test_answerable_case_blocked_by_guardrails_is_not_answered(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr, _, _, _ = await _world(session, chunk_index)
    case = EvalCase(question="How many leave days?", run_as_group_ids=[str(hr.id)])
    config = RagConfig.model_validate(
        {
            "guardrails": {
                "classifier_model": "blocker",
                "user_daily_cost_usd": 0,
                "installation_daily_cost_usd": 0,
            }
        }
    )
    blocker = FakeListChatModel(
        responses=['{"prompt_injection": true, "exfiltration": false, "off_topic": false}']
    )
    outcome = await run_case(
        create_sessionmaker(engine),
        chat_deps(chunk_index, models={"blocker": blocker}),
        config,
        case,
        [hr],
        run_id=uuid.uuid4(),
    )
    assert outcome.outcome == "blocked"
    metrics = deterministic_metrics(case, outcome)
    assert (metrics["answered"], metrics["idk_correct"]) == (0.0, None)


class _Metric:
    def __init__(self, value: float | Exception) -> None:
        self.value = value
        self.calls: list[dict[str, Any]] = []

    async def ascore(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self.value, Exception):
            raise self.value
        return SimpleNamespace(value=self.value)


def _scorer(**overrides: float | Exception) -> tuple[RagasScorer, dict[str, _Metric]]:
    names = (
        "faithfulness",
        "answer_relevancy",
        "precision_with_ref",
        "precision_without_ref",
        "context_recall",
        "answer_correctness",
    )
    metrics = {n: _Metric(overrides.get(n, 0.8)) for n in names}
    return RagasScorer(**metrics), metrics  # type: ignore[arg-type]


async def test_scorer_picks_metrics_by_available_reference() -> None:
    scorer, metrics = _scorer()
    with_ref = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference="r", answered=True)
    )
    assert set(with_ref) == {
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevancy",
        "answer_correctness",
    }
    assert metrics["precision_without_ref"].calls == []

    scorer, metrics = _scorer()
    no_ref = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference=None, answered=True)
    )
    assert set(no_ref) == {"context_precision", "faithfulness", "answer_relevancy"}
    assert metrics["precision_with_ref"].calls == []

    scorer, _ = _scorer()
    refused = await scorer.score(
        ScoreInput(question="q", answer="", contexts=[], reference="r", answered=False)
    )
    assert refused == {}


async def test_scorer_failed_metric_is_none() -> None:
    scorer, _ = _scorer(faithfulness=RuntimeError("judge down"))
    scores = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference=None, answered=True)
    )
    assert scores["faithfulness"] is None
    assert scores["answer_relevancy"] == 0.8


def test_build_ragas_scorer_offline() -> None:
    settings = Settings(_env_file=None, jwt_secret="x" * 40, openai_api_key="sk-test")
    assert isinstance(build_ragas_scorer(settings, "gpt-5-mini"), RagasScorer)


async def test_scorer_none_and_nan_values_become_none() -> None:
    scorer, _ = _scorer(faithfulness=float("nan"))
    scorer.answer_relevancy = _Metric(0.8)
    scorer.answer_relevancy.value = None  # type: ignore[assignment]
    scores = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference=None, answered=True)
    )
    assert scores["faithfulness"] is None and scores["answer_relevancy"] is None
    assert scores["context_precision"] == 0.8
