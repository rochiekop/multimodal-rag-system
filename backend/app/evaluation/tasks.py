"""Celery task for eval runs, on its own queue so long runs never delay ingestion."""

import asyncio
import uuid

from qdrant_client import AsyncQdrantClient

from app.chat.wiring import build_chat_deps
from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.tracing import setup_tracing
from app.evaluation.runs import execute_run
from app.evaluation.scoring import build_ragas_scorer
from app.ingestion.index import ChunkIndex
from app.ingestion.tasks import celery_app

EVAL_QUEUE = "evaluation"


async def _run(run_id: uuid.UUID) -> None:
    settings = get_settings()
    setup_tracing(settings)  # eval.case spans go to Phoenix when configured
    engine = create_engine(settings.database_url)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimensions)
        await execute_run(
            run_id,
            sessionmaker=create_sessionmaker(engine),
            deps=build_chat_deps(settings, index),
            scorer_factory=lambda judge: build_ragas_scorer(settings, judge),
        )
    finally:
        await qdrant.close()
        await engine.dispose()


@celery_app.task(name="evaluation.run_eval")
def run_eval(run_id: str) -> None:
    asyncio.run(_run(uuid.UUID(run_id)))


def enqueue_eval(run_id: uuid.UUID) -> None:
    run_eval.apply_async(args=[str(run_id)], queue=EVAL_QUEUE)
