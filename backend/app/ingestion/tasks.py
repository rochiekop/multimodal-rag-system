"""Celery worker entry point: celery -A app.ingestion.tasks worker -Q ingestion"""

import asyncio
import uuid
from typing import Any

from celery import Celery
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.storage import LocalFileStore
from app.documents.models import DocumentStatus
from app.ingestion.index import ChunkIndex
from app.ingestion.parse import parse_document
from app.ingestion.pipeline import IngestionDeps, run_ingestion
from app.ingestion.scan import scan_bytes
from app.llm.gateway import describe_image, get_embeddings, get_vision_model
from app.llm.sparse import embed_sparse_documents

MAX_RETRIES = 3

celery_app = Celery("rag")
celery_app.conf.update(
    broker_url=get_settings().redis_url,
    task_default_queue="ingestion",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


def build_deps(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    qdrant: AsyncQdrantClient,
) -> IngestionDeps:
    embeddings = get_embeddings(settings)
    vision = get_vision_model(settings)

    async def scan(data: bytes) -> None:
        if settings.clamav_enabled:
            await scan_bytes(settings.clamav_host, settings.clamav_port, data)

    async def describe(png: bytes) -> str:
        return await describe_image(vision, png)

    return IngestionDeps(
        sessionmaker=sessionmaker,
        store=LocalFileStore(settings.files_dir),
        index=ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimensions),
        scan=scan,
        parse=parse_document,
        describe_image=describe,
        embed_dense=embeddings.aembed_documents,
        embed_sparse=embed_sparse_documents,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )


async def _run(version_id: uuid.UUID, final_attempt: bool) -> DocumentStatus:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        deps = build_deps(settings, create_sessionmaker(engine), qdrant)
        return await run_ingestion(version_id, deps, final_attempt=final_attempt)
    finally:
        await qdrant.close()
        await engine.dispose()


@celery_app.task(bind=True, name="ingestion.ingest_version", max_retries=MAX_RETRIES)
def ingest_version(self: Any, version_id: str) -> str:
    final_attempt = self.request.retries >= MAX_RETRIES
    try:
        status = asyncio.run(_run(uuid.UUID(version_id), final_attempt))
    except Exception as exc:  # run_ingestion re-raises only transient errors
        raise self.retry(exc=exc, countdown=30 * 2**self.request.retries) from exc
    return status.value


def enqueue_ingestion(version_id: uuid.UUID) -> None:
    ingest_version.delay(str(version_id))
