import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# Must be set before app modules read settings.
os.environ.setdefault("RAG_JWT_SECRET", "test-only-secret-" + "x" * 32)

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

import app.models as _models  # noqa: F401  (aliased so the `app` fixture doesn't shadow it)
from app.core.config import Settings
from app.core.db import Base, create_engine, create_sessionmaker
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """One throwaway Postgres per test run, migrated to head with the real migrations."""
    with PostgresContainer("postgres:17.6-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        alembic_cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(alembic_cfg, "head")
        yield url


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    container = DockerContainer("qdrant/qdrant:v1.19.1").with_exposed_ports(6333)
    with container:
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(6333)}"
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{url}/readyz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Qdrant test container did not become ready")
            time.sleep(0.5)
        yield url


@pytest.fixture
def settings(postgres_url: str, qdrant_url: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url=postgres_url,
        login_max_failed_attempts=3,
        qdrant_url=qdrant_url,
        qdrant_collection=f"test_{uuid.uuid4().hex[:12]}",
        files_dir=str(tmp_path / "files"),
        embedding_dimensions=8,
        clamav_enabled=False,
    )


@pytest_asyncio.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings.database_url)
    yield engine
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    if tables:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with create_sessionmaker(engine)() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def app(settings: Settings, engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    # Depends on `engine` so tables are truncated after each API test.
    application = create_app(settings)
    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
