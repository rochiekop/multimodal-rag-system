import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.api.router import api_router
from app.chat.wiring import build_chat_deps
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.storage import LocalFileStore
from app.core.tracing import setup_tracing
from app.guardrails.limits import RateLimiter
from app.ingestion.index import ChunkIndex


def _enqueue_with_celery(version_id: uuid.UUID) -> None:
    from app.ingestion.tasks import enqueue_ingestion  # imported lazily: Celery + pipeline

    enqueue_ingestion(version_id)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.env != "test":  # tests keep pytest's log capture
        configure_logging(settings.log_level)
    setup_tracing(settings)
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()
        await application.state.rate_limiter.redis.aclose()
        await application.state.index.client.close()

    show_docs = settings.env != "prod"
    app = FastAPI(
        title="Multimodal RAG API",
        lifespan=lifespan,
        docs_url="/api/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if show_docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.store = LocalFileStore(settings.files_dir)
    app.state.index = ChunkIndex(
        AsyncQdrantClient(url=settings.qdrant_url),
        settings.qdrant_collection,
        settings.embedding_dimensions,
    )
    app.state.chat_deps = build_chat_deps(settings, app.state.index)
    app.state.rate_limiter = RateLimiter(
        Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
    )
    app.state.enqueue = _enqueue_with_celery
    app.add_middleware(RequestIdMiddleware)
    app.include_router(api_router)
    return app
