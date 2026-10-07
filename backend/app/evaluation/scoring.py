"""Answer-quality scoring with Ragas (spec §7.1), behind a small protocol so tests use fakes.
A metric that fails returns None for that case; the run continues."""

import asyncio
import logging
import math
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import SecretStr

from app.core.config import Settings

logger = logging.getLogger(__name__)

METRICS = (
    "hit_rate",
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
    "answer_correctness",
)


@dataclass(frozen=True)
class ScoreInput:
    question: str
    answer: str
    contexts: list[str]
    reference: str | None  # the expected answer, if the case has one
    answered: bool  # an actual answer was generated


class Scorer(Protocol):
    async def score(self, item: ScoreInput) -> dict[str, float | None]: ...


class RagasScorer:
    def __init__(
        self,
        *,
        faithfulness: Any,
        answer_relevancy: Any,
        precision_with_ref: Any,
        precision_without_ref: Any,
        context_recall: Any,
        answer_correctness: Any,
    ) -> None:
        self.faithfulness = faithfulness
        self.answer_relevancy = answer_relevancy
        self.precision_with_ref = precision_with_ref
        self.precision_without_ref = precision_without_ref
        self.context_recall = context_recall
        self.answer_correctness = answer_correctness

    async def score(self, item: ScoreInput) -> dict[str, float | None]:
        jobs: dict[str, Awaitable[Any]] = {}
        q, a, ctx, ref = item.question, item.answer, item.contexts, item.reference
        if ctx and ref:
            jobs["context_precision"] = self.precision_with_ref.ascore(
                user_input=q, reference=ref, retrieved_contexts=ctx
            )
            jobs["context_recall"] = self.context_recall.ascore(
                user_input=q, retrieved_contexts=ctx, reference=ref
            )
        if item.answered:
            if ctx and not ref:
                jobs["context_precision"] = self.precision_without_ref.ascore(
                    user_input=q, response=a, retrieved_contexts=ctx
                )
            if ctx:
                jobs["faithfulness"] = self.faithfulness.ascore(
                    user_input=q, response=a, retrieved_contexts=ctx
                )
            jobs["answer_relevancy"] = self.answer_relevancy.ascore(user_input=q, response=a)
            if ref:
                jobs["answer_correctness"] = self.answer_correctness.ascore(
                    user_input=q, response=a, reference=ref
                )
        names = list(jobs)
        outcomes = await asyncio.gather(*jobs.values(), return_exceptions=True)
        scores: dict[str, float | None] = {}
        for name, outcome in zip(names, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning("Metric %s failed: %s", name, outcome)
                scores[name] = None
                continue
            try:
                value = float(outcome.value)
            except (TypeError, ValueError):
                value = math.nan
            if math.isfinite(value):
                scores[name] = value
            else:
                logger.warning("Metric %s returned no usable value: %r", name, outcome.value)
                scores[name] = None
        return scores


def build_ragas_scorer(
    settings: Settings, judge_model: str, api_key: SecretStr | None = None
) -> RagasScorer:
    """Real Ragas metrics judged by `judge_model` (OpenAI). Built offline; calls happen later."""
    from openai import AsyncOpenAI
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    key = api_key or settings.openai_api_key
    if key is None:
        raise RuntimeError(
            "No OpenAI API key: save one in admin Settings or set RAG_OPENAI_API_KEY"
        )
    client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=2, timeout=120)
    llm = llm_factory(judge_model, provider="openai", client=client)
    embeddings = OpenAIEmbeddings(client=client, model=settings.embedding_model)
    return RagasScorer(
        faithfulness=Faithfulness(llm=llm),
        answer_relevancy=AnswerRelevancy(llm=llm, embeddings=embeddings),
        precision_with_ref=ContextPrecisionWithReference(llm=llm),
        precision_without_ref=ContextPrecisionWithoutReference(llm=llm),
        context_recall=ContextRecall(llm=llm),
        answer_correctness=AnswerCorrectness(llm=llm, embeddings=embeddings),
    )
