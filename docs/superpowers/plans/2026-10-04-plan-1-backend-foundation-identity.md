# Plan 1 — Backend Foundation & Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running, tested FastAPI backend in Docker with PostgreSQL, Alembic migrations, structured logging with request IDs, users/groups/roles, an append-only audit log, JWT authentication with lockout and forced password change, admin APIs for users/groups/audit, and a `create-superadmin` CLI.

**Architecture:** One Python package `app` under `backend/`, split into modules (`core`, `users`, `audit`, `auth`, `api`). Each module exposes a small interface. Service functions take an `AsyncSession` and never commit; API routes and the CLI commit. API routers are thin and translate service errors into HTTP errors with the shape `{"detail": {"code": ..., "message": ...}}`. Access tokens are sent as `Authorization: Bearer`. Refresh tokens live in an httpOnly `SameSite=Strict` cookie scoped to `/api/auth`.

**Tech Stack:** Python 3.12, uv, FastAPI, Uvicorn, Pydantic v2 + pydantic-settings, SQLAlchemy 2 (async) + asyncpg, Alembic, argon2-cffi, PyJWT, structlog, pytest + pytest-asyncio + httpx + testcontainers, ruff, mypy, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md`

## Where this plan fits

The v1 spec is delivered as a series of plans. Each plan produces working, tested software, and each later plan is written just before it is executed, against the code that exists by then:

1. **Backend foundation & identity** (this plan): spec §2.2 core/auth/users/audit, §6.2, §6.3, §6.9, §8.2 (partial), §9 (backend CI)
2. **Documents & ingestion:** collections, access groups, uploads, MinIO, Redis + Celery, ClamAV, Gotenberg, Docling, enrichment, chunking, embeddings, Qdrant indexing, chunk inspector API (spec §3, §6.1). *Check that the chosen MinIO image is still published; if not, use another S3-compatible store.*
3. **Retrieval & answering:** LLM gateway, RagConfig, hybrid search, rerank, confidence check, SSE chat, citations, conversations, feedback, Phoenix tracing (spec §4, §7.2)
4. **Guardrails & abuse protection** (spec §5)
5. **Evaluation & review queue** (spec §7.1)
6. **Frontend foundation + user app:** Next.js + shadcn init, login block, forced password change, chat, history, source viewer (spec §6.4, §6.8)
7. **Admin console:** `dashboard-01` and all admin pages (spec §6.5)
8. **Production packaging:** Caddy, full compose, backup/restore, Playwright E2E, CI expansion (spec §8, §9)

## Global Constraints

- Python **3.12** (`requires-python = ">=3.12,<3.13"`); dependencies managed with **uv**; `uv.lock` committed.
- Environment variables use the prefix **`RAG_`**; `RAG_JWT_SECRET` is required and must be ≥ 32 characters.
- Roles are exactly `user`, `admin`, `super_admin` (spec §6.2). `admin` manages only `user` accounts; `super_admin` manages everyone.
- **Admins create users directly**; new users **must change their password at first login**. No email, no self-registration (spec §6.3).
- Passwords are hashed with **Argon2**; short-lived JWT access tokens; refresh tokens in **httpOnly** cookies; sessions are revoked on suspension or role change (spec §6.3).
- Login lockout after repeated failed attempts (spec §5.3). Defaults: **5 attempts, 15-minute lock**.
- Audit log is **append-only** and records actor, action, target, details (JSON), timestamp and request ID (spec §6.9).
- Every API route has server-side auth and role checks, enforced by an automated test (spec §5.3, §9).
- Logs are structured JSON with a request ID (spec §7.2).
- Docker images: multi-stage, **non-root**, pinned versions, health checks (spec §8.3). Migrations run automatically on API start (spec §8.2).
- Service functions never call `commit()`; routes and the CLI do.

## Review Focus

1. **Username typed with different case or spaces** (`" Alice "` vs `alice`): login and creation treat them as the same account. Tests in Task 6 (`test_username_is_normalized_and_unique_case_insensitively`) and Task 7 (`test_username_is_case_and_space_insensitive`).
2. **Suspended user still holding a valid access token:** the very next request is rejected with 401, not after the token expires. Test in Task 9 (`test_suspended_user_token_is_rejected_immediately`).
3. **Password change on one device:** old refresh tokens from other sessions stop working. Test in Task 8 (`test_change_password_revokes_old_refresh_token`).
4. **Correct password while locked, then after the lock expires:** rejected during the lock, accepted after it. Test in Task 7 (`test_lock_blocks_correct_password_until_expiry`).
5. **Admin privilege escalation:** an `admin` cannot create, promote or edit `admin`/`super_admin` accounts, cannot change their own role and cannot suspend themselves. Tests in Task 6 and Task 9 (`test_admin_cannot_promote_user_to_admin_via_api`).

---

## File structure (end state of this plan)

```
.gitattributes                         # LF line endings
.gitignore
Makefile                               # up, down, logs, test, lint, create-superadmin
.github/workflows/ci.yml               # lint + tests + docker build
deploy/
  docker-compose.yml                   # postgres + api (later plans add services)
  .env.example
backend/
  .python-version                      # 3.12
  pyproject.toml                       # deps, ruff, mypy, pytest config
  uv.lock
  Dockerfile
  .dockerignore
  alembic.ini
  migrations/
    env.py
    script.py.mako
    versions/0001_users_and_groups.py
    versions/0002_audit_log.py
  app/
    __init__.py
    main.py                            # create_app() factory
    models.py                          # imports every ORM model (metadata registry)
    cli.py                             # python -m app.cli create-superadmin
    core/
      __init__.py
      config.py                        # Settings, get_settings, get_app_settings
      db.py                            # Base, engine, sessionmaker, get_session
      logging.py                       # structlog JSON, request_id_var, RequestIdMiddleware
      security.py                      # Argon2 hashing, password strength
    users/
      __init__.py
      models.py                        # Role, User, Group, user_groups
      schemas.py                       # Pydantic in/out models
      service.py                       # user & group use cases
    audit/
      __init__.py
      models.py                        # AuditLog
      schemas.py
      service.py                       # record(), list_entries()
    auth/
      __init__.py
      tokens.py                        # create_token, decode_token
      service.py                       # authenticate, change_password
      deps.py                          # current_user, require_admin, ...
    api/
      __init__.py
      errors.py                        # api_error()
      router.py                        # /api router
      health.py
      auth.py
      admin_users.py
      admin_audit.py
  tests/
    __init__.py
    conftest.py
    factories.py
    test_config.py
    test_database.py
    test_health.py
    test_security.py
    test_user_models.py
    test_audit.py
    test_users_service.py
    test_tokens.py
    test_auth_service.py
    test_auth_api.py
    test_route_protection.py
    test_admin_api.py
    test_cli.py
```

All commands below run from the repository root unless a step says `cd backend`.

---

### Task 1: Backend project scaffold and settings

**Files:**
- Create: `.gitattributes`, `.gitignore`, `backend/.python-version`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/tests/__init__.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `app.core.config.Settings` (fields: `env: Literal["dev","test","prod"]`, `log_level: str`, `database_url: str`, `jwt_secret: SecretStr`, `jwt_access_ttl_seconds: int`, `jwt_refresh_ttl_seconds: int`, `login_max_failed_attempts: int`, `login_lockout_seconds: int`, `cors_origins: list[str]`, `cookie_secure: bool`), `get_settings() -> Settings` (cached), `get_app_settings(request: Request) -> Settings`

- [ ] **Step 1: Create repo hygiene files**

`.gitattributes`:
```
* text=auto eol=lf
*.png binary
*.jpg binary
*.pdf binary
```

`.gitignore`:
```
# Python
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/

# Node
node_modules/
.next/

# Env and local data
.env
deploy/.env
*.log

# OS / editors
.DS_Store
Thumbs.db
.idea/
.vscode/
```

- [ ] **Step 2: Initialize the uv project and add dependencies**

```bash
mkdir -p backend/app/core backend/tests
cd backend
uv init --bare --name multimodal-rag-backend --python 3.12
uv python pin 3.12
uv add fastapi "uvicorn[standard]" pydantic-settings "sqlalchemy[asyncio]" asyncpg alembic argon2-cffi pyjwt structlog
uv add --dev pytest pytest-asyncio httpx "testcontainers[postgres]" ruff mypy
```

Then edit `backend/pyproject.toml` so that `requires-python` and the tool sections read as follows. Keep the `dependencies` and `[dependency-groups]` lists exactly as `uv add` wrote them:

```toml
[project]
name = "multimodal-rag-backend"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
# dependencies = [...]  (written by uv add, keep as is)

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC"]

[tool.ruff.lint.per-file-ignores]
"tests/conftest.py" = ["E402"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

Run `uv sync` after editing.

Create empty `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/tests/__init__.py`.

- [ ] **Step 3: Write the failing test**

`backend/tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG_SECRET = "s" * 40


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_JWT_SECRET", STRONG_SECRET)
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("RAG_LOGIN_MAX_FAILED_ATTEMPTS", "7")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"
    assert settings.jwt_secret.get_secret_value() == STRONG_SECRET
    assert settings.login_max_failed_attempts == 7


def test_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_JWT_SECRET", STRONG_SECRET)
    settings = Settings(_env_file=None)

    assert settings.login_max_failed_attempts == 5
    assert settings.login_lockout_seconds == 900
    assert settings.jwt_access_ttl_seconds == 900
    assert settings.cookie_secure is True


def test_jwt_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None)


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None, jwt_secret="short")


def test_secret_is_not_leaked_in_repr() -> None:
    settings = Settings(_env_file=None, jwt_secret=STRONG_SECRET)
    assert STRONG_SECRET not in repr(settings)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 5: Write the implementation**

`backend/app/core/config.py`:
```python
from functools import lru_cache
from typing import Literal, cast

from fastapi import Request
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an env var with the RAG_ prefix."""

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"

    jwt_secret: SecretStr
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 7

    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 900

    cors_origins: list[str] = Field(default_factory=list)
    cookie_secure: bool = True

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("RAG_JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment


def get_app_settings(request: Request) -> Settings:
    """FastAPI dependency: the Settings instance the app was created with."""
    return cast(Settings, request.app.state.settings)
```

- [ ] **Step 6: Run tests to verify they pass, then lint**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: 5 passed

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: no errors (run `uv run ruff format .` first if the format check fails)

- [ ] **Step 7: Commit**

```bash
git add .gitattributes .gitignore backend
git commit -m "feat(backend): scaffold uv project and settings"
```

---

### Task 2: Database layer, Alembic and the test harness

**Files:**
- Create: `backend/app/core/db.py`, `backend/app/models.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/.gitkeep`, `backend/tests/conftest.py`
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings` (Task 1)
- Produces:
  - `app.core.db.Base` (DeclarativeBase with naming convention)
  - `create_engine(url: str) -> AsyncEngine`
  - `create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]` (`expire_on_commit=False`)
  - `get_session(request: Request) -> AsyncIterator[AsyncSession]` (FastAPI dependency; uses `request.app.state.sessionmaker`)
  - `app.models`: importing it registers every table on `Base.metadata`
  - Test fixtures: `postgres_url` (session), `settings`, `engine`, `session`. Tables are truncated after each test.

- [ ] **Step 1: Write the database module and model registry**

`backend/app/core/db.py`:
```python
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Routes commit explicitly; anything uncommitted is rolled back."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session
```

`backend/app/models.py`:
```python
"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""
```

- [ ] **Step 2: Write the Alembic configuration**

`backend/alembic.ini`:
```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/migrations/env.py`:
```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (registers all tables)
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from app.core.config import get_settings

    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

`backend/migrations/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create the empty file `backend/migrations/versions/.gitkeep`.

- [ ] **Step 3: Write the shared test fixtures**

`backend/tests/conftest.py`:
```python
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# Must be set before app modules read settings.
os.environ.setdefault("RAG_JWT_SECRET", "test-only-secret-" + "x" * 32)
os.environ.setdefault("RAG_ENV", "test")

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

import app.models as _models  # noqa: F401  (registers every table; aliased so the `app` fixture doesn't shadow it)
from app.core.config import Settings
from app.core.db import Base, create_engine, create_sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = "postgres:17.6-alpine"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """One throwaway Postgres per test run, migrated to head with the real migrations."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        alembic_cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(alembic_cfg, "head")
        yield url


@pytest.fixture
def settings(postgres_url: str) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url=postgres_url,
        cookie_secure=False,
        login_max_failed_attempts=3,
        login_lockout_seconds=900,
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
```

- [ ] **Step 4: Write the failing test**

`backend/tests/test_database.py`:
```python
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import Base


async def test_session_executes_queries(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    """Fails when an ORM model changes without a matching Alembic migration."""
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    assert diff == []
```

- [ ] **Step 5: Run the tests**

Docker Desktop must be running (testcontainers starts Postgres).

Run: `cd backend && uv run pytest tests/test_database.py -v`
Expected: 2 passed. If it fails with a Docker connection error, start Docker Desktop and re-run.

- [ ] **Step 6: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: no errors

```bash
git add backend
git commit -m "feat(backend): add async database layer, alembic and test harness"
```

---

### Task 3: Logging, request IDs, app factory and health endpoint

**Files:**
- Create: `backend/app/core/logging.py`, `backend/app/api/__init__.py`, `backend/app/api/errors.py`, `backend/app/api/health.py`, `backend/app/api/router.py`, `backend/app/main.py`
- Modify: `backend/tests/conftest.py` (add `app` and `client` fixtures)
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings` (Task 1); `create_engine`, `create_sessionmaker` (Task 2)
- Produces:
  - `app.core.logging.request_id_var: ContextVar[str | None]`
  - `configure_logging(level: str) -> None`
  - `RequestIdMiddleware` (ASGI)
  - `app.api.errors.api_error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None, **extra: Any) -> HTTPException`
  - `app.api.router.api_router` (prefix `/api`)
  - `app.main.create_app(settings: Settings | None = None) -> FastAPI`, which sets `app.state.settings`, `app.state.engine` and `app.state.sessionmaker`
  - `GET /api/health` → 200 `{"status": "ok", "database": "ok"}` or 503 `{"status": "degraded", "database": "error"}`
  - Test fixtures `app` and `client` (httpx `AsyncClient`, base URL `http://test`)

- [ ] **Step 1: Add the app and client fixtures**

Append to `backend/tests/conftest.py`. Merge the new imports into the existing import block:
```python
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_health.py`:
```python
import re

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_database_failure() -> None:
    settings = Settings(
        _env_file=None,
        jwt_secret="x" * 40,
        database_url="postgresql+asyncpg://rag:rag@127.0.0.1:1/rag",
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/health")
    await app.state.engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error"}


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_is_generated_when_missing(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "bad id; drop table"})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Write the logging module**

`backend/app/core/logging.py`:
```python
import logging
import re
import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.typing import EventDict, WrappedLogger

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
_log = structlog.get_logger("http")


def _add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )


class RequestIdMiddleware:
    """Assigns every HTTP request an ID (trusted from X-Request-ID when well-formed),
    exposes it via request_id_var, returns it in the response, and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for name, value in scope["headers"]:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex

        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _log.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            request_id_var.reset(token)
```

- [ ] **Step 5: Write the API error helper, health router, API router and app factory**

`backend/app/api/__init__.py`: empty file.

`backend/app/api/errors.py`:
```python
from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> HTTPException:
    """Every API error uses the body shape {"detail": {"code", "message", ...extra}}."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
        headers=headers,
    )
```

`backend/app/api/health.py`:
```python
import asyncio

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    database = "ok"
    try:
        async with asyncio.timeout(3):
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        database = "error"

    healthy = database == "ok"
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "database": database}
```

`backend/app/api/router.py`:
```python
from fastapi import APIRouter

from app.api import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
```

`backend/app/main.py`:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import RequestIdMiddleware, configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

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

    app.add_middleware(RequestIdMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    app.include_router(api_router)
    return app
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: 5 passed

- [ ] **Step 7: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: no errors

```bash
git add backend
git commit -m "feat(backend): add app factory, JSON logging, request IDs and health check"
```

---

### Task 4: Users and groups data model with password hashing

**Files:**
- Create: `backend/app/core/security.py`, `backend/app/users/__init__.py`, `backend/app/users/models.py`, `backend/migrations/versions/0001_users_and_groups.py`, `backend/tests/factories.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_security.py`, `backend/tests/test_user_models.py`

**Interfaces:**
- Consumes: `Base` (Task 2)
- Produces:
  - `app.core.security`: `hash_password(password: str) -> str`, `verify_password(password_hash: str, password: str) -> bool`, `validate_password_strength(password: str) -> None` (raises `WeakPasswordError(ValueError)`)
  - `app.users.models`: `Role(StrEnum)` with `USER="user"`, `ADMIN="admin"`, `SUPER_ADMIN="super_admin"`; `ROLE_RANK: dict[Role, int]`; `Group` (`id: UUID`, `name: str`, `description: str`, `created_at`); `User` (`id: UUID`, `username: str`, `full_name: str`, `password_hash: str`, `role: str`, `is_active: bool`, `must_change_password: bool`, `failed_login_count: int`, `locked_until: datetime | None`, `token_version: int`, `created_at`, `groups: list[Group]`)
  - `tests/factories.py`: `DEFAULT_PASSWORD`, `make_user(session, *, username="alice", role=Role.USER, password=DEFAULT_PASSWORD, must_change_password=False, is_active=True, groups=()) -> User`, `make_group(session, name="engineering") -> Group`

- [ ] **Step 1: Write the failing security tests**

`backend/tests/test_security.py`:
```python
import pytest

from app.core.security import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
    verify_password,
)


def test_hash_and_verify_roundtrip() -> None:
    password_hash = hash_password("correct-horse-42")
    assert password_hash != "correct-horse-42"
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct-horse-42")
    assert not verify_password(password_hash, "wrong-horse-42")


def test_verify_with_garbage_hash_returns_false() -> None:
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short1", "at least 12"),
        ("a" * 12, "letter and a digit"),
        ("1" * 12, "letter and a digit"),
        ("a1" * 65, "at most 128"),
    ],
)
def test_weak_passwords_are_rejected(password: str, message: str) -> None:
    with pytest.raises(WeakPasswordError, match=message):
        validate_password_strength(password)


def test_strong_password_is_accepted() -> None:
    validate_password_strength("correct-horse-42")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 3: Implement security helpers**

`backend/app/core/security.py`:
```python
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


class WeakPasswordError(ValueError):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise WeakPasswordError("Password must contain at least one letter and a digit")
```

Run: `cd backend && uv run pytest tests/test_security.py -v`
Expected: 7 passed

- [ ] **Step 4: Write the failing model tests and factories**

`backend/tests/factories.py`:
```python
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.users.models import Group, Role, User

DEFAULT_PASSWORD = "correct-horse-42"


async def make_group(session: AsyncSession, name: str = "engineering") -> Group:
    group = Group(name=name, description="")
    session.add(group)
    await session.commit()
    return group


async def make_user(
    session: AsyncSession,
    *,
    username: str = "alice",
    role: Role = Role.USER,
    password: str = DEFAULT_PASSWORD,
    must_change_password: bool = False,
    is_active: bool = True,
    groups: Iterable[Group] = (),
) -> User:
    user = User(
        username=username,
        full_name=username.title(),
        password_hash=hash_password(password),
        role=role.value,
        must_change_password=must_change_password,
        is_active=is_active,
        groups=list(groups),
    )
    session.add(user)
    await session.commit()
    return user
```

`backend/tests/test_user_models.py`:
```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import ROLE_RANK, Group, Role, User


async def test_user_defaults_and_groups(session: AsyncSession) -> None:
    session.add(
        User(
            username="bob",
            full_name="Bob",
            password_hash="x",
            role="user",
            groups=[Group(name="hr")],
        )
    )
    await session.commit()

    loaded = await session.scalar(
        select(User).where(User.username == "bob").execution_options(populate_existing=True)
    )
    assert loaded is not None
    assert loaded.is_active is True
    assert loaded.must_change_password is True
    assert loaded.failed_login_count == 0
    assert loaded.token_version == 0
    assert loaded.locked_until is None
    assert loaded.created_at is not None
    assert [g.name for g in loaded.groups] == ["hr"]


async def test_role_must_be_valid(session: AsyncSession) -> None:
    session.add(User(username="eve", full_name="Eve", password_hash="x", role="root"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_username_is_unique(session: AsyncSession) -> None:
    session.add(User(username="dup", full_name="A", password_hash="x", role="user"))
    await session.commit()
    session.add(User(username="dup", full_name="B", password_hash="x", role="user"))
    with pytest.raises(IntegrityError):
        await session.commit()


def test_role_rank_orders_roles() -> None:
    assert ROLE_RANK[Role.USER] < ROLE_RANK[Role.ADMIN] < ROLE_RANK[Role.SUPER_ADMIN]
```

Run: `cd backend && uv run pytest tests/test_user_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.users'`

- [ ] **Step 5: Implement the models**

`backend/app/users/__init__.py`: empty file.

`backend/app/users/models.py`:
```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Table, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


ROLE_RANK: dict[Role, int] = {Role.USER: 0, Role.ADMIN: 1, Role.SUPER_ADMIN: 2}

user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Uuid, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Group(Base):
    __tablename__ = "groups"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin', 'super_admin')", name="role_valid"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=True)
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Incremented to revoke every token issued before (suspension, role change, password change).
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    groups: Mapped[list[Group]] = relationship(secondary=user_groups, lazy="selectin")
```

Replace `backend/app/models.py` with:
```python
"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.users.models import Group, User, user_groups

__all__ = ["Group", "User", "user_groups"]
```

- [ ] **Step 6: Write the migration**

`backend/migrations/versions/0001_users_and_groups.py`:
```python
"""users and groups

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_groups_name")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'admin', 'super_admin')", name=op.f("ck_users_role_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_user_groups_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_groups_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id", name=op.f("pk_user_groups")),
    )


def downgrade() -> None:
    op.drop_table("user_groups")
    op.drop_table("users")
    op.drop_table("groups")
```

Delete `backend/migrations/versions/.gitkeep`.

- [ ] **Step 7: Run the tests, including the migration-drift test**

Run: `cd backend && uv run pytest tests/test_user_models.py tests/test_database.py tests/test_security.py -v`
Expected: all passed. If `test_models_match_migrations` fails, the diff it prints shows which column or constraint in the migration differs from the model. Fix the migration to match the model.

- [ ] **Step 8: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`

```bash
git add backend
git commit -m "feat(users): add user/group models, migration and argon2 password hashing"
```

---

### Task 5: Append-only audit log

**Files:**
- Create: `backend/app/audit/__init__.py`, `backend/app/audit/models.py`, `backend/app/audit/schemas.py`, `backend/app/audit/service.py`, `backend/migrations/versions/0002_audit_log.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_audit.py`

**Interfaces:**
- Consumes: `Base` (Task 2), `request_id_var` (Task 3), `User` (Task 4)
- Produces:
  - `app.audit.models.AuditLog` (`id: int`, `created_at`, `actor_id: UUID | None`, `actor_username: str | None`, `action: str`, `target_type: str | None`, `target_id: str | None`, `detail: dict[str, Any]`, `request_id: str | None`)
  - `app.audit.service.record(session, *, action: str, actor: User | None = None, target_type: str | None = None, target_id: str | UUID | None = None, detail: dict[str, Any] | None = None) -> AuditLog`. It adds and flushes but does not commit, and reads the request ID from `request_id_var`.
  - `app.audit.service.list_entries(session, *, limit: int = 50, before_id: int | None = None, action: str | None = None, actor_id: UUID | None = None) -> list[AuditLog]`, newest first
  - `app.audit.schemas.AuditEntryOut` (Pydantic, `from_attributes`)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_audit.py`:
```python
import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.audit.models import AuditLog
from app.core.logging import request_id_var
from tests.factories import make_user


async def test_record_captures_actor_target_detail_and_request_id(session: AsyncSession) -> None:
    actor = await make_user(session, username="carol")
    token = request_id_var.set("req-42")
    try:
        entry = await audit.record(
            session,
            action="user.created",
            actor=actor,
            target_type="user",
            target_id=actor.id,
            detail={"role": "user"},
        )
        await session.commit()
    finally:
        request_id_var.reset(token)

    assert entry.id is not None
    assert entry.created_at is not None
    assert entry.actor_id == actor.id
    assert entry.actor_username == "carol"
    assert entry.target_id == str(actor.id)
    assert entry.detail == {"role": "user"}
    assert entry.request_id == "req-42"


async def test_system_actions_have_no_actor(session: AsyncSession) -> None:
    entry = await audit.record(session, action="system.event")
    await session.commit()
    assert entry.actor_id is None
    assert entry.detail == {}


async def test_audit_rows_cannot_be_updated(session: AsyncSession) -> None:
    entry = await audit.record(session, action="test.event")
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(
            update(AuditLog).where(AuditLog.id == entry.id).values(action="tampered")
        )
    await session.rollback()


async def test_audit_rows_cannot_be_deleted(session: AsyncSession) -> None:
    entry = await audit.record(session, action="test.event")
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(AuditLog).where(AuditLog.id == entry.id))
    await session.rollback()


async def test_list_entries_newest_first_with_filters_and_paging(session: AsyncSession) -> None:
    actor = await make_user(session, username="dave")
    for i in range(5):
        await audit.record(session, action="a.even" if i % 2 == 0 else "a.odd", actor=actor)
    await audit.record(session, action="a.even")
    await session.commit()

    newest = await audit.list_entries(session, limit=3)
    assert [e.id for e in newest] == [6, 5, 4]

    older = await audit.list_entries(session, limit=10, before_id=4)
    assert [e.id for e in older] == [3, 2, 1]

    evens = await audit.list_entries(session, action="a.even")
    assert [e.id for e in evens] == [6, 5, 3, 1]

    by_actor = await audit.list_entries(session, action="a.even", actor_id=actor.id)
    assert [e.id for e in by_actor] == [5, 3, 1]
```

Run: `cd backend && uv run pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.audit'`

- [ ] **Step 2: Implement the model, schema and service**

`backend/app/audit/__init__.py`: empty file.

`backend/app/audit/models.py`:
```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    """Append-only: a database trigger rejects UPDATE and DELETE (migration 0002).
    actor_id has no foreign key on purpose, so audit rows outlive any user change."""

    __tablename__ = "audit_log"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
```

`backend/app/audit/schemas.py`:
```python
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_username: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any]
    request_id: str | None
```

`backend/app/audit/service.py`:
```python
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.logging import request_id_var

if TYPE_CHECKING:
    from app.users.models import User


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit entry to the caller's transaction. The caller commits."""
    entry = AuditLog(
        actor_id=actor.id if actor is not None else None,
        actor_username=actor.username if actor is not None else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail or {},
        request_id=request_id_var.get(),
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(
    session: AsyncSession,
    *,
    limit: int = 50,
    before_id: int | None = None,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    return list((await session.scalars(query)).all())
```

Replace `backend/app/models.py` with:
```python
"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.audit.models import AuditLog
from app.users.models import Group, User, user_groups

__all__ = ["AuditLog", "Group", "User", "user_groups"]
```

- [ ] **Step 3: Write the migration with the append-only trigger**

`backend/migrations/versions/0002_audit_log.py`:
```python
"""audit log (append-only)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"])
    op.execute(
        """
        CREATE FUNCTION audit_log_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_update_delete ON audit_log")
    op.execute("DROP FUNCTION audit_log_block_mutation()")
    op.drop_index(op.f("ix_audit_log_actor_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
```

Note: `TRUNCATE` (used by the test fixtures and by operators for maintenance) does not fire row-level triggers, by design.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_audit.py tests/test_database.py -v`
Expected: all passed

- [ ] **Step 5: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`

```bash
git add backend
git commit -m "feat(audit): add append-only audit log with request IDs"
```

---

### Task 6: User and group management service

**Files:**
- Create: `backend/app/users/service.py`
- Test: `backend/tests/test_users_service.py`

**Interfaces:**
- Consumes: `User`, `Group`, `Role`, `ROLE_RANK` (Task 4); `hash_password`, `validate_password_strength`, `WeakPasswordError` (Task 4); `audit.record` (Task 5)
- Produces (all in `app.users.service`; none of them commit):
  - Errors: `UserServiceError(Exception)` with `.code: str` and `.message: str`; subclasses `NotFound` (`"not_found"`), `UsernameTaken` (`"username_taken"`), `InvalidUsername` (`"invalid_username"`), `GroupNotFound` (`"group_not_found"`), `GroupNameTaken` (`"group_name_taken"`), `PermissionDenied` (`"forbidden"`)
  - `normalize_username(raw: str) -> str`
  - `can_manage(actor: User, target_role: Role) -> bool`
  - `create_user(session, *, actor: User | None, username: str, full_name: str, password: str, role: Role = Role.USER, group_ids: Iterable[UUID] = (), must_change_password: bool = True) -> User`. `actor=None` means the system (CLI).
  - `update_user(session, *, actor: User, user_id: UUID, full_name: str | None = None, role: Role | None = None, group_ids: Iterable[UUID] | None = None) -> User`
  - `set_active(session, *, actor: User, user_id: UUID, active: bool) -> User`
  - `unlock_user(session, *, actor: User, user_id: UUID) -> User`
  - `reset_password(session, *, actor: User, user_id: UUID, new_password: str) -> User`
  - `list_users(session) -> list[User]`
  - `create_group(session, *, actor: User | None, name: str, description: str = "") -> Group`
  - `update_group(session, *, actor: User, group_id: UUID, name: str | None = None, description: str | None = None) -> Group`
  - `list_groups(session) -> list[Group]`
  - Audit actions: `user.created`, `user.updated`, `user.suspended`, `user.reactivated`, `user.unlocked`, `user.password_reset`, `group.created`, `group.updated`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_users_service.py`:
```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.security import WeakPasswordError, verify_password
from app.users import service as users
from app.users.models import Role
from tests.factories import make_group, make_user

STRONG = "brand-new-pass-77"


async def test_system_creates_user_with_normalized_username_and_audit(
    session: AsyncSession,
) -> None:
    group = await make_group(session, "hr")
    user = await users.create_user(
        session,
        actor=None,
        username="  New.Person ",
        full_name=" New Person ",
        password=STRONG,
        group_ids=[group.id],
    )
    await session.commit()

    assert user.username == "new.person"
    assert user.full_name == "New Person"
    assert user.role == "user"
    assert user.must_change_password is True
    assert verify_password(user.password_hash, STRONG)
    assert [g.name for g in user.groups] == ["hr"]
    entries = await audit.list_entries(session, action="user.created")
    assert entries[0].target_id == str(user.id)
    assert "password" not in str(entries[0].detail)


async def test_username_is_normalized_and_unique_case_insensitively(
    session: AsyncSession,
) -> None:
    await make_user(session, username="alice")
    with pytest.raises(users.UsernameTaken):
        await users.create_user(
            session, actor=None, username=" ALICE ", full_name="A", password=STRONG
        )


@pytest.mark.parametrize("bad", ["ab", "has space", "émile", "x" * 65, "semi;colon"])
async def test_invalid_usernames_rejected(session: AsyncSession, bad: str) -> None:
    with pytest.raises(users.InvalidUsername):
        await users.create_user(session, actor=None, username=bad, full_name="X", password=STRONG)


async def test_weak_password_rejected(session: AsyncSession) -> None:
    with pytest.raises(WeakPasswordError):
        await users.create_user(
            session, actor=None, username="weak", full_name="W", password="short"
        )


async def test_unknown_group_rejected(session: AsyncSession) -> None:
    with pytest.raises(users.GroupNotFound):
        await users.create_user(
            session,
            actor=None,
            username="nogroup",
            full_name="N",
            password=STRONG,
            group_ids=[uuid.uuid4()],
        )


async def test_admin_can_create_user_but_not_admin(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    created = await users.create_user(
        session, actor=admin, username="worker", full_name="W", password=STRONG
    )
    assert created.role == "user"
    with pytest.raises(users.PermissionDenied):
        await users.create_user(
            session,
            actor=admin,
            username="admin2",
            full_name="A",
            password=STRONG,
            role=Role.ADMIN,
        )


async def test_super_admin_can_create_admin(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    created = await users.create_user(
        session, actor=root, username="admin2", full_name="A", password=STRONG, role=Role.ADMIN
    )
    assert created.role == "admin"


async def test_regular_user_cannot_manage_anyone(session: AsyncSession) -> None:
    plain = await make_user(session, username="plain")
    with pytest.raises(users.PermissionDenied):
        await users.create_user(
            session, actor=plain, username="other", full_name="O", password=STRONG
        )


async def test_update_role_bumps_token_version(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    target = await make_user(session, username="target")
    updated = await users.update_user(session, actor=root, user_id=target.id, role=Role.ADMIN)
    assert updated.role == "admin"
    assert updated.token_version == 1


async def test_admin_cannot_edit_or_promote_admins(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    other_admin = await make_user(session, username="admin2", role=Role.ADMIN)
    plain = await make_user(session, username="plain")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=other_admin.id, full_name="X")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=plain.id, role=Role.ADMIN)


async def test_cannot_change_own_role(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    with pytest.raises(users.PermissionDenied, match="own role"):
        await users.update_user(session, actor=root, user_id=root.id, role=Role.USER)


async def test_update_groups_replaces_membership(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    hr = await make_group(session, "hr")
    eng = await make_group(session, "eng")
    target = await make_user(session, username="target", groups=[hr])
    updated = await users.update_user(session, actor=admin, user_id=target.id, group_ids=[eng.id])
    assert [g.name for g in updated.groups] == ["eng"]


async def test_update_unknown_user_is_not_found(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    with pytest.raises(users.NotFound):
        await users.update_user(session, actor=admin, user_id=uuid.uuid4(), full_name="X")


async def test_suspend_revokes_tokens_and_reactivate(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    suspended = await users.set_active(session, actor=admin, user_id=target.id, active=False)
    assert suspended.is_active is False
    assert suspended.token_version == 1
    reactivated = await users.set_active(session, actor=admin, user_id=target.id, active=True)
    assert reactivated.is_active is True
    actions = [e.action for e in await audit.list_entries(session)]
    assert actions[:2] == ["user.reactivated", "user.suspended"]


async def test_cannot_suspend_yourself(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    with pytest.raises(users.PermissionDenied, match="yourself"):
        await users.set_active(session, actor=admin, user_id=admin.id, active=False)


async def test_unlock_clears_lockout(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    target.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    target.failed_login_count = 2
    await session.commit()
    unlocked = await users.unlock_user(session, actor=admin, user_id=target.id)
    assert unlocked.locked_until is None
    assert unlocked.failed_login_count == 0


async def test_reset_password_forces_change_and_revokes(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    reset = await users.reset_password(
        session, actor=admin, user_id=target.id, new_password="temporary-pass-11"
    )
    assert verify_password(reset.password_hash, "temporary-pass-11")
    assert reset.must_change_password is True
    assert reset.token_version == 1


async def test_groups_create_update_and_unique_names(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    group = await users.create_group(session, actor=admin, name=" Finance ", description="money")
    assert group.name == "Finance"
    with pytest.raises(users.GroupNameTaken):
        await users.create_group(session, actor=admin, name="Finance")
    renamed = await users.update_group(session, actor=admin, group_id=group.id, name="Accounting")
    assert renamed.name == "Accounting"
    assert [g.name for g in await users.list_groups(session)] == ["Accounting"]
```

Run: `cd backend && uv run pytest tests/test_users_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'service' from 'app.users'`

- [ ] **Step 2: Implement the service**

`backend/app/users/service.py`:
```python
"""User and group management use cases. Functions flush but never commit; callers commit."""

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.security import hash_password, validate_password_strength
from app.users.models import Group, Role, User

_USERNAME_RE = re.compile(r"[a-z0-9._-]{3,64}")


class UserServiceError(Exception):
    code = "user_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(UserServiceError):
    code = "not_found"


class UsernameTaken(UserServiceError):
    code = "username_taken"


class InvalidUsername(UserServiceError):
    code = "invalid_username"


class GroupNotFound(UserServiceError):
    code = "group_not_found"


class GroupNameTaken(UserServiceError):
    code = "group_name_taken"


class PermissionDenied(UserServiceError):
    code = "forbidden"


def normalize_username(raw: str) -> str:
    username = raw.strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise InvalidUsername(
            "Username must be 3-64 characters using letters, digits, '.', '_' or '-'"
        )
    return username


def can_manage(actor: User, target_role: Role) -> bool:
    """super_admin manages everyone; admin manages only regular users."""
    actor_role = Role(actor.role)
    if actor_role is Role.SUPER_ADMIN:
        return True
    return actor_role is Role.ADMIN and target_role is Role.USER


def _ensure_can_manage(actor: User | None, target_role: Role) -> None:
    if actor is not None and not can_manage(actor, target_role):
        raise PermissionDenied(f"Your role cannot manage {target_role.value} accounts")


async def _get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def _load_groups(session: AsyncSession, group_ids: Iterable[uuid.UUID]) -> list[Group]:
    wanted = list(dict.fromkeys(group_ids))
    if not wanted:
        return []
    groups = list((await session.scalars(select(Group).where(Group.id.in_(wanted)))).all())
    if len(groups) != len(wanted):
        raise GroupNotFound("One or more groups do not exist")
    return sorted(groups, key=lambda g: g.name)


async def create_user(
    session: AsyncSession,
    *,
    actor: User | None,
    username: str,
    full_name: str,
    password: str,
    role: Role = Role.USER,
    group_ids: Iterable[uuid.UUID] = (),
    must_change_password: bool = True,
) -> User:
    _ensure_can_manage(actor, role)
    normalized = normalize_username(username)
    validate_password_strength(password)
    if await session.scalar(select(User.id).where(User.username == normalized)) is not None:
        raise UsernameTaken(f"Username '{normalized}' is already taken")

    user = User(
        username=normalized,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role.value,
        must_change_password=must_change_password,
        groups=await _load_groups(session, group_ids),
    )
    session.add(user)
    await session.flush()
    await audit.record(
        session,
        action="user.created",
        actor=actor,
        target_type="user",
        target_id=user.id,
        detail={
            "username": normalized,
            "role": role.value,
            "group_ids": [str(g.id) for g in user.groups],
        },
    )
    return user


async def update_user(
    session: AsyncSession,
    *,
    actor: User,
    user_id: uuid.UUID,
    full_name: str | None = None,
    role: Role | None = None,
    group_ids: Iterable[uuid.UUID] | None = None,
) -> User:
    user = await _get_user(session, user_id)
    _ensure_can_manage(actor, Role(user.role))
    changes: dict[str, object] = {}

    if full_name is not None:
        user.full_name = full_name.strip()
        changes["full_name"] = user.full_name
    if role is not None and role.value != user.role:
        if user.id == actor.id:
            raise PermissionDenied("You cannot change your own role")
        _ensure_can_manage(actor, role)
        user.role = role.value
        user.token_version += 1
        changes["role"] = role.value
    if group_ids is not None:
        user.groups = await _load_groups(session, group_ids)
        changes["group_ids"] = [str(g.id) for g in user.groups]

    await session.flush()
    await audit.record(
        session,
        action="user.updated",
        actor=actor,
        target_type="user",
        target_id=user.id,
        detail=changes,
    )
    return user


async def set_active(
    session: AsyncSession, *, actor: User, user_id: uuid.UUID, active: bool
) -> User:
    user = await _get_user(session, user_id)
    if not active and user.id == actor.id:
        raise PermissionDenied("You cannot suspend yourself")
    _ensure_can_manage(actor, Role(user.role))
    if user.is_active == active:
        return user

    user.is_active = active
    if not active:
        user.token_version += 1
    await session.flush()
    await audit.record(
        session,
        action="user.reactivated" if active else "user.suspended",
        actor=actor,
        target_type="user",
        target_id=user.id,
    )
    return user


async def unlock_user(session: AsyncSession, *, actor: User, user_id: uuid.UUID) -> User:
    user = await _get_user(session, user_id)
    _ensure_can_manage(actor, Role(user.role))
    user.locked_until = None
    user.failed_login_count = 0
    await session.flush()
    await audit.record(
        session, action="user.unlocked", actor=actor, target_type="user", target_id=user.id
    )
    return user


async def reset_password(
    session: AsyncSession, *, actor: User, user_id: uuid.UUID, new_password: str
) -> User:
    user = await _get_user(session, user_id)
    _ensure_can_manage(actor, Role(user.role))
    validate_password_strength(new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.token_version += 1
    await session.flush()
    await audit.record(
        session,
        action="user.password_reset",
        actor=actor,
        target_type="user",
        target_id=user.id,
    )
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def _ensure_group_name_free(
    session: AsyncSession, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    query = select(Group.id).where(Group.name == name)
    if exclude_id is not None:
        query = query.where(Group.id != exclude_id)
    if await session.scalar(query) is not None:
        raise GroupNameTaken(f"Group '{name}' already exists")


async def create_group(
    session: AsyncSession, *, actor: User | None, name: str, description: str = ""
) -> Group:
    clean_name = name.strip()
    await _ensure_group_name_free(session, clean_name)
    group = Group(name=clean_name, description=description.strip())
    session.add(group)
    await session.flush()
    await audit.record(
        session,
        action="group.created",
        actor=actor,
        target_type="group",
        target_id=group.id,
        detail={"name": clean_name},
    )
    return group


async def update_group(
    session: AsyncSession,
    *,
    actor: User,
    group_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise NotFound("Group not found")
    changes: dict[str, object] = {}
    if name is not None:
        clean_name = name.strip()
        await _ensure_group_name_free(session, clean_name, exclude_id=group.id)
        group.name = clean_name
        changes["name"] = clean_name
    if description is not None:
        group.description = description.strip()
        changes["description"] = group.description
    await session.flush()
    await audit.record(
        session,
        action="group.updated",
        actor=actor,
        target_type="group",
        target_id=group.id,
        detail=changes,
    )
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.scalars(select(Group).order_by(Group.name))).all())
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_users_service.py -v`
Expected: all passed

- [ ] **Step 4: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`

```bash
git add backend
git commit -m "feat(users): add user and group management service with role rules"
```

---

### Task 7: Tokens, authentication with lockout, and password change

**Files:**
- Create: `backend/app/auth/__init__.py`, `backend/app/auth/tokens.py`, `backend/app/auth/service.py`
- Test: `backend/tests/test_tokens.py`, `backend/tests/test_auth_service.py`

**Interfaces:**
- Consumes: `Settings` (Task 1); `User` (Task 4); `hash_password`, `verify_password`, `validate_password_strength`, `WeakPasswordError` (Task 4); `audit.record` (Task 5)
- Produces:
  - `app.auth.tokens`: `TokenType = Literal["access", "refresh"]`; `TokenClaims(user_id: UUID, role: str, token_version: int, token_type: TokenType)` (frozen dataclass); `TokenError(Exception)`; `create_token(*, user: User, token_type: TokenType, settings: Settings, now: datetime | None = None) -> str`; `decode_token(token: str, *, expected_type: TokenType, settings: Settings) -> TokenClaims`
  - `app.auth.service`: `AuthError(Exception)` with `.code`; `InvalidCredentials` (`"invalid_credentials"`), `AccountLocked` (`"account_locked"`, attribute `.until: datetime`), `AccountDisabled` (`"account_disabled"`); `authenticate(session, *, username: str, password: str, settings: Settings, now: datetime | None = None) -> User`; `change_password(session, *, user: User, current_password: str, new_password: str) -> User`
  - Audit actions: `auth.login_succeeded`, `auth.login_failed`, `auth.account_locked`, `auth.password_changed`
  - `authenticate` changes rows (failed counters, audit) **before raising**, so the caller must commit in both the success and the failure path.

- [ ] **Step 1: Write the failing token tests**

`backend/tests/test_tokens.py`:
```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.tokens import TokenError, create_token, decode_token
from app.core.config import Settings
from app.users.models import User


def _settings() -> Settings:
    return Settings(_env_file=None, jwt_secret="k" * 40, jwt_access_ttl_seconds=60)


def _user() -> User:
    return User(id=uuid.uuid4(), username="u", role="admin", token_version=3)


def test_roundtrip_access_token() -> None:
    settings, user = _settings(), _user()
    claims = decode_token(
        create_token(user=user, token_type="access", settings=settings),
        expected_type="access",
        settings=settings,
    )
    assert claims.user_id == user.id
    assert claims.role == "admin"
    assert claims.token_version == 3
    assert claims.token_type == "access"


def test_refresh_token_is_not_accepted_as_access() -> None:
    settings = _settings()
    token = create_token(user=_user(), token_type="refresh", settings=settings)
    with pytest.raises(TokenError, match="type"):
        decode_token(token, expected_type="access", settings=settings)


def test_expired_token_rejected() -> None:
    settings = _settings()
    past = datetime.now(UTC) - timedelta(minutes=5)
    token = create_token(user=_user(), token_type="access", settings=settings, now=past)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access", settings=settings)


def test_token_signed_with_other_secret_rejected() -> None:
    other = Settings(_env_file=None, jwt_secret="z" * 40)
    token = create_token(user=_user(), token_type="access", settings=other)
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access", settings=_settings())


def test_garbage_token_rejected() -> None:
    with pytest.raises(TokenError):
        decode_token("not.a.jwt", expected_type="access", settings=_settings())
```

Run: `cd backend && uv run pytest tests/test_tokens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 2: Implement tokens**

`backend/app/auth/__init__.py`: empty file.

`backend/app/auth/tokens.py`:
```python
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import Settings
from app.users.models import User

TokenType = Literal["access", "refresh"]
_ALGORITHM = "HS256"


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    token_version: int
    token_type: TokenType


def create_token(
    *, user: User, token_type: TokenType, settings: Settings, now: datetime | None = None
) -> str:
    issued_at = now or datetime.now(UTC)
    ttl = (
        settings.jwt_access_ttl_seconds
        if token_type == "access"
        else settings.jwt_refresh_ttl_seconds
    )
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "tv": user.token_version,
        "typ": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_token(token: str, *, expected_type: TokenType, settings: Settings) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise TokenError("Unexpected token type")
    try:
        return TokenClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            role=str(payload.get("role", "")),
            token_version=int(payload["tv"]),
            token_type=expected_type,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("Malformed token claims") from exc
```

Run: `cd backend && uv run pytest tests/test_tokens.py -v`
Expected: 5 passed

- [ ] **Step 3: Write the failing authentication tests**

`backend/tests/test_auth_service.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth import service as auth
from app.core.config import Settings
from app.core.security import WeakPasswordError, verify_password
from tests.factories import DEFAULT_PASSWORD, make_user


async def test_successful_login_resets_counters(session: AsyncSession, settings: Settings) -> None:
    user = await make_user(session, username="alice")
    user.failed_login_count = 2
    await session.commit()

    result = await auth.authenticate(
        session, username="alice", password=DEFAULT_PASSWORD, settings=settings
    )
    await session.commit()

    assert result.id == user.id
    assert result.failed_login_count == 0
    assert (await audit.list_entries(session))[0].action == "auth.login_succeeded"


async def test_username_is_case_and_space_insensitive(
    session: AsyncSession, settings: Settings
) -> None:
    await make_user(session, username="alice")
    user = await auth.authenticate(
        session, username="  Alice ", password=DEFAULT_PASSWORD, settings=settings
    )
    assert user.username == "alice"


async def test_unknown_user_is_invalid_credentials(
    session: AsyncSession, settings: Settings
) -> None:
    with pytest.raises(auth.InvalidCredentials):
        await auth.authenticate(session, username="ghost", password="x", settings=settings)
    await session.commit()
    entry = (await audit.list_entries(session))[0]
    assert entry.action == "auth.login_failed"
    assert entry.detail["reason"] == "unknown_user"


async def test_wrong_password_counts_and_locks_after_max(
    session: AsyncSession, settings: Settings
) -> None:
    # settings fixture: login_max_failed_attempts=3, login_lockout_seconds=900
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    for _ in range(2):
        with pytest.raises(auth.InvalidCredentials):
            await auth.authenticate(
                session, username="alice", password="wrong", settings=settings, now=now
            )
    assert user.failed_login_count == 2

    with pytest.raises(auth.AccountLocked) as locked:
        await auth.authenticate(
            session, username="alice", password="wrong", settings=settings, now=now
        )
    await session.commit()

    assert locked.value.until == now + timedelta(seconds=900)
    assert user.locked_until == now + timedelta(seconds=900)
    assert user.failed_login_count == 0
    actions = [e.action for e in await audit.list_entries(session)]
    assert actions[0] == "auth.account_locked"


async def test_lock_blocks_correct_password_until_expiry(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    user.locked_until = now + timedelta(minutes=15)
    await session.commit()

    with pytest.raises(auth.AccountLocked):
        await auth.authenticate(
            session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=now
        )

    later = now + timedelta(minutes=15, seconds=1)
    result = await auth.authenticate(
        session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=later
    )
    assert result.locked_until is None


async def test_disabled_user_with_correct_password(
    session: AsyncSession, settings: Settings
) -> None:
    await make_user(session, username="alice", is_active=False)
    with pytest.raises(auth.AccountDisabled):
        await auth.authenticate(
            session, username="alice", password=DEFAULT_PASSWORD, settings=settings
        )


async def test_disabled_user_with_wrong_password_looks_like_bad_credentials(
    session: AsyncSession, settings: Settings
) -> None:
    await make_user(session, username="alice", is_active=False)
    with pytest.raises(auth.InvalidCredentials):
        await auth.authenticate(session, username="alice", password="wrong", settings=settings)


async def test_change_password(session: AsyncSession) -> None:
    user = await make_user(session, username="alice", must_change_password=True)
    changed = await auth.change_password(
        session, user=user, current_password=DEFAULT_PASSWORD, new_password="fresh-secret-99"
    )
    assert verify_password(changed.password_hash, "fresh-secret-99")
    assert changed.must_change_password is False
    assert changed.token_version == 1


async def test_change_password_requires_current_password(session: AsyncSession) -> None:
    user = await make_user(session, username="alice")
    with pytest.raises(auth.InvalidCredentials):
        await auth.change_password(
            session, user=user, current_password="wrong", new_password="fresh-secret-99"
        )


async def test_change_password_rejects_same_or_weak(session: AsyncSession) -> None:
    user = await make_user(session, username="alice")
    with pytest.raises(WeakPasswordError, match="differ"):
        await auth.change_password(
            session, user=user, current_password=DEFAULT_PASSWORD, new_password=DEFAULT_PASSWORD
        )
    with pytest.raises(WeakPasswordError):
        await auth.change_password(
            session, user=user, current_password=DEFAULT_PASSWORD, new_password="short"
        )
```

Run: `cd backend && uv run pytest tests/test_auth_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'service' from 'app.auth'`

- [ ] **Step 4: Implement the authentication service**

`backend/app/auth/service.py`:
```python
"""Login and password-change use cases. Functions never commit.
authenticate() records failures before raising, so callers commit on failure too."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.security import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.users.models import User

# Verified against when the username does not exist, so response time doesn't reveal it.
_DUMMY_HASH = hash_password("timing-equalizer-password-0")


class AuthError(Exception):
    code = "auth_error"


class InvalidCredentials(AuthError):
    code = "invalid_credentials"


class AccountDisabled(AuthError):
    code = "account_disabled"


class AccountLocked(AuthError):
    code = "account_locked"

    def __init__(self, until: datetime) -> None:
        super().__init__(f"Account locked until {until.isoformat()}")
        self.until = until


async def authenticate(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
    now: datetime | None = None,
) -> User:
    now = now or datetime.now(UTC)
    normalized = username.strip().lower()
    user = await session.scalar(select(User).where(User.username == normalized))

    if user is None:
        verify_password(_DUMMY_HASH, password)
        await audit.record(
            session,
            action="auth.login_failed",
            detail={"username": normalized[:64], "reason": "unknown_user"},
        )
        raise InvalidCredentials()

    if user.locked_until is not None and user.locked_until > now:
        await audit.record(
            session,
            action="auth.login_failed",
            actor=user,
            target_type="user",
            target_id=user.id,
            detail={"reason": "locked"},
        )
        raise AccountLocked(user.locked_until)

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        await audit.record(
            session,
            action="auth.login_failed",
            actor=user,
            target_type="user",
            target_id=user.id,
            detail={"reason": "bad_password", "failed_count": user.failed_login_count},
        )
        if user.failed_login_count >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            user.failed_login_count = 0
            await audit.record(
                session,
                action="auth.account_locked",
                actor=user,
                target_type="user",
                target_id=user.id,
                detail={"until": user.locked_until.isoformat()},
            )
            raise AccountLocked(user.locked_until)
        raise InvalidCredentials()

    if not user.is_active:
        await audit.record(
            session,
            action="auth.login_failed",
            actor=user,
            target_type="user",
            target_id=user.id,
            detail={"reason": "disabled"},
        )
        raise AccountDisabled()

    user.failed_login_count = 0
    user.locked_until = None
    await audit.record(
        session, action="auth.login_succeeded", actor=user, target_type="user", target_id=user.id
    )
    return user


async def change_password(
    session: AsyncSession, *, user: User, current_password: str, new_password: str
) -> User:
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentials()
    if new_password == current_password:
        raise WeakPasswordError("New password must differ from the current one")
    validate_password_strength(new_password)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.token_version += 1  # signs out every other session
    await session.flush()
    await audit.record(
        session, action="auth.password_changed", actor=user, target_type="user", target_id=user.id
    )
    return user
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_tokens.py tests/test_auth_service.py -v`
Expected: all passed

- [ ] **Step 6: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`

```bash
git add backend
git commit -m "feat(auth): add JWT tokens, login with lockout and password change"
```

---

### Task 8: Auth API, auth dependencies and route-protection guard

**Files:**
- Create: `backend/app/auth/deps.py`, `backend/app/users/schemas.py`, `backend/app/api/auth.py`
- Modify: `backend/app/api/router.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_auth_api.py`, `backend/tests/test_route_protection.py`

**Interfaces:**
- Consumes: `get_session` (Task 2); `get_app_settings` (Task 1); `api_error` (Task 3); tokens and auth service (Task 7); `User`, `Role`, `ROLE_RANK` (Task 4)
- Produces:
  - `app.auth.deps`: `SessionDep`, `SettingsDep` (Annotated aliases); `current_user_allow_password_change(...) -> User` (valid access token, active user, matching token version); `current_user(...) -> User` (also rejects `must_change_password` with 403 `password_change_required`); `require_admin(...) -> User`; `require_super_admin(...) -> User`; aliases `CurrentUser`, `AdminUser`, `SuperAdminUser`
  - `app.users.schemas`: `GroupOut`, `UserOut`, `UserCreate`, `UserUpdate`, `PasswordReset`, `GroupCreate`, `GroupUpdate`
  - Endpoints: `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout` (204), `GET /api/auth/me`, `POST /api/auth/change-password`. Login, refresh and change-password return `TokenResponse {access_token, token_type: "bearer", expires_in, must_change_password, user: UserOut}` and set the `rag_refresh` cookie (httpOnly, SameSite=Strict, Path=/api/auth, Secure per settings).
  - Error codes: 401 `not_authenticated` / `invalid_token` / `invalid_credentials`; 423 `account_locked` (+`locked_until`); 403 `account_disabled` / `password_change_required` / `forbidden`; 422 `weak_password`
  - `tests/factories.py` gains `login(client, username, password=DEFAULT_PASSWORD) -> str` and `bearer(token) -> dict[str, str]`
  - `tests/test_route_protection.py`: `PUBLIC_ROUTES` allowlist that later plans extend only on purpose

- [ ] **Step 1: Add the test helpers**

Append to `backend/tests/factories.py`. Add `from httpx import AsyncClient` to its imports:
```python
async def login(client: AsyncClient, username: str, password: str = DEFAULT_PASSWORD) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def refresh_cookie(response_set_cookie: str) -> str:
    """Extract the rag_refresh value from a Set-Cookie header."""
    first = response_set_cookie.split(";", 1)[0]
    name, _, value = first.partition("=")
    assert name == "rag_refresh"
    return value
```

- [ ] **Step 2: Write the failing API tests**

`backend/tests/test_auth_api.py`:
```python
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user, refresh_cookie


async def test_login_returns_tokens_and_secure_refresh_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["must_change_password"] is False
    assert body["user"]["username"] == "alice"
    assert "password_hash" not in body["user"]

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("rag_refresh=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api/auth" in cookie


async def test_login_wrong_password(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


async def test_failed_attempts_persist_and_lock(client: AsyncClient, session: AsyncSession) -> None:
    user = await make_user(session, username="alice")
    for _ in range(2):
        await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert response.status_code == 423
    assert response.json()["detail"]["code"] == "account_locked"
    assert "locked_until" in response.json()["detail"]

    await session.refresh(user)
    assert user.locked_until is not None


async def test_disabled_account(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice", is_active=False)
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "account_disabled"


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "not_authenticated"


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me", headers=bearer("garbage"))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_token"


async def test_me_returns_current_user(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    token = await login(client, "alice")
    response = await client.get("/api/auth/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["username"] == "alice"


async def test_refresh_issues_new_access_token(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    login_response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD}
    )
    cookie_value = refresh_cookie(login_response.headers["set-cookie"])

    response = await client.post(
        "/api/auth/refresh", headers={"Cookie": f"rag_refresh={cookie_value}"}
    )
    assert response.status_code == 200
    me = await client.get("/api/auth/me", headers=bearer(response.json()["access_token"]))
    assert me.status_code == 200


async def test_refresh_without_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 401


async def test_access_token_cannot_be_used_as_refresh(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    access = await login(client, "alice")
    response = await client.post("/api/auth/refresh", headers={"Cookie": f"rag_refresh={access}"})
    assert response.status_code == 401


async def test_logout_clears_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/auth/logout")
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("rag_refresh=")
    assert "max-age=0" in cookie


async def test_forced_password_change_flow(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="newbie", must_change_password=True)
    login_response = await client.post(
        "/api/auth/login", json={"username": "newbie", "password": DEFAULT_PASSWORD}
    )
    assert login_response.json()["must_change_password"] is True
    token = login_response.json()["access_token"]

    # /me is allowed so the frontend can show the change-password screen
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 200

    weak = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422
    assert weak.json()["detail"]["code"] == "weak_password"

    changed = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "fresh-secret-99"},
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False

    # the token issued before the change is revoked; the new one works
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    new_token = changed.json()["access_token"]
    assert (await client.get("/api/auth/me", headers=bearer(new_token))).status_code == 200


async def test_change_password_wrong_current(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    token = await login(client, "alice")
    response = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": "wrong", "new_password": "fresh-secret-99"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_credentials"


async def test_change_password_revokes_old_refresh_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    # "device A" logs in and keeps its refresh cookie
    device_a = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD}
    )
    old_refresh = refresh_cookie(device_a.headers["set-cookie"])

    # "device B" changes the password
    token_b = await login(client, "alice")
    await client.post(
        "/api/auth/change-password",
        headers=bearer(token_b),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "fresh-secret-99"},
    )

    response = await client.post(
        "/api/auth/refresh", headers={"Cookie": f"rag_refresh={old_refresh}"}
    )
    assert response.status_code == 401
```

`backend/tests/test_route_protection.py`:
```python
from collections.abc import Callable, Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.auth.deps import current_user_allow_password_change
from app.core.config import Settings
from app.main import create_app

# Routes reachable without a valid access token. Adding to this list must be a
# deliberate, reviewed decision.
PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
}


def _all_calls(dependant: Dependant) -> Iterator[Callable[..., Any] | None]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _all_calls(dependency)


def _api_routes() -> list[APIRoute]:
    app = create_app(
        Settings(
            _env_file=None,
            jwt_secret="x" * 40,
            database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x",
        )
    )
    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_every_non_public_route_requires_authentication() -> None:
    unprotected = [
        f"{method} {route.path}"
        for route in _api_routes()
        for method in sorted(route.methods)
        if (method, route.path) not in PUBLIC_ROUTES
        and current_user_allow_password_change not in set(_all_calls(route.dependant))
    ]
    assert unprotected == []


def test_public_allowlist_has_no_stale_entries() -> None:
    existing = {(m, r.path) for r in _api_routes() for m in r.methods}
    assert PUBLIC_ROUTES <= existing
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_auth_api.py tests/test_route_protection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.deps'`

- [ ] **Step 4: Implement the schemas**

`backend/app/users/schemas.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.users.models import Role


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    full_name: str
    role: Role
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    groups: list[GroupOut]
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=128)
    role: Role = Role.USER
    group_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    group_ids: list[uuid.UUID] | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
```

- [ ] **Step 5: Implement the auth dependencies**

`backend/app/auth/deps.py`:
```python
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.auth.tokens import TokenError, decode_token
from app.core.config import Settings, get_app_settings
from app.core.db import get_session
from app.users.models import ROLE_RANK, Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]

_bearer = HTTPBearer(auto_error=False)
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


async def current_user_allow_password_change(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Any authenticated, active user, including one who still must change their password."""
    if credentials is None:
        raise api_error(401, "not_authenticated", "Missing bearer token", headers=_WWW_AUTH)
    try:
        claims = decode_token(credentials.credentials, expected_type="access", settings=settings)
    except TokenError:
        raise api_error(
            401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH
        ) from None

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise api_error(401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH)
    return user


async def current_user(
    user: Annotated[User, Depends(current_user_allow_password_change)],
) -> User:
    if user.must_change_password:
        raise api_error(
            403, "password_change_required", "You must change your password before continuing"
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _ensure_role(user: User, minimum: Role) -> User:
    if ROLE_RANK[Role(user.role)] < ROLE_RANK[minimum]:
        raise api_error(403, "forbidden", "Your role does not allow this action")
    return user


async def require_admin(user: CurrentUser) -> User:
    return _ensure_role(user, Role.ADMIN)


async def require_super_admin(user: CurrentUser) -> User:
    return _ensure_role(user, Role.SUPER_ADMIN)


AdminUser = Annotated[User, Depends(require_admin)]
SuperAdminUser = Annotated[User, Depends(require_super_admin)]
```

- [ ] **Step 6: Implement the auth router**

`backend/app/api/auth.py`:
```python
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.errors import api_error
from app.auth.deps import SessionDep, SettingsDep, current_user_allow_password_change
from app.auth.service import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    authenticate,
    change_password,
)
from app.auth.tokens import TokenError, create_token, decode_token
from app.core.config import Settings
from app.core.security import WeakPasswordError
from app.users.models import User
from app.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "rag_refresh"
REFRESH_COOKIE_PATH = "/api/auth"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    must_change_password: bool
    user: UserOut


def _issue_tokens(user: User, settings: Settings, response: Response) -> TokenResponse:
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(user=user, token_type="refresh", settings=settings),
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )
    return TokenResponse(
        access_token=create_token(user=user, token_type="access", settings=settings),
        expires_in=settings.jwt_access_ttl_seconds,
        must_change_password=user.must_change_password,
        user=UserOut.model_validate(user),
    )


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    try:
        user = await authenticate(
            session, username=body.username, password=body.password, settings=settings
        )
    except AccountLocked as exc:
        await session.commit()  # persist the lock and audit entries
        raise api_error(
            423, exc.code, "Account is temporarily locked", locked_until=exc.until.isoformat()
        ) from None
    except AccountDisabled as exc:
        await session.commit()
        raise api_error(403, exc.code, "Account is disabled") from None
    except InvalidCredentials as exc:
        await session.commit()
        raise api_error(401, exc.code, "Invalid username or password") from None

    await session.commit()
    return _issue_tokens(user, settings, response)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise api_error(401, "not_authenticated", "Missing refresh token")
    try:
        claims = decode_token(token, expected_type="refresh", settings=settings)
    except TokenError:
        raise api_error(401, "invalid_token", "Invalid or expired refresh token") from None

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise api_error(401, "invalid_token", "Invalid or expired refresh token")
    return _issue_tokens(user, settings, response)


@router.post("/logout", status_code=204)
async def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


@router.get("/me")
async def me(user: Annotated[User, Depends(current_user_allow_password_change)]) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password")
async def change_password_route(
    body: ChangePasswordRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    user: Annotated[User, Depends(current_user_allow_password_change)],
) -> TokenResponse:
    try:
        await change_password(
            session,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except InvalidCredentials as exc:
        raise api_error(400, exc.code, "Current password is incorrect") from None
    except WeakPasswordError as exc:
        raise api_error(422, "weak_password", str(exc)) from None
    await session.commit()
    return _issue_tokens(user, settings, response)
```

Replace `backend/app/api/router.py` with:
```python
from fastapi import APIRouter

from app.api import auth, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_auth_api.py tests/test_route_protection.py -v`
Expected: all passed

- [ ] **Step 8: Lint, full suite, commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`
Expected: no lint errors; all tests pass

```bash
git add backend
git commit -m "feat(auth): add login/refresh/logout/me/change-password API and route guard test"
```

---

### Task 9: Admin API for users, groups and the audit log

**Files:**
- Create: `backend/app/api/admin_users.py`, `backend/app/api/admin_audit.py`
- Modify: `backend/app/api/router.py`, `backend/tests/test_route_protection.py`
- Test: `backend/tests/test_admin_api.py`

**Interfaces:**
- Consumes: `app.users.service` (Task 6); `app.users.schemas` (Task 8); `AdminUser`, `SessionDep` (Task 8); `audit.list_entries`, `AuditEntryOut` (Task 5); `api_error` (Task 3); `WeakPasswordError` (Task 4)
- Produces endpoints (all require `admin` or higher):
  - `GET /api/admin/users` → `list[UserOut]`
  - `POST /api/admin/users` (201) body `UserCreate` → `UserOut`
  - `PATCH /api/admin/users/{user_id}` body `UserUpdate` → `UserOut`
  - `POST /api/admin/users/{user_id}/suspend` | `/reactivate` | `/unlock` → `UserOut`
  - `POST /api/admin/users/{user_id}/reset-password` body `PasswordReset` → `UserOut`
  - `GET /api/admin/groups` → `list[GroupOut]`; `POST /api/admin/groups` (201) body `GroupCreate`; `PATCH /api/admin/groups/{group_id}` body `GroupUpdate`
  - `GET /api/admin/audit?limit=50&before_id=&action=&actor_id=` → `list[AuditEntryOut]`
  - Service error mapping: `NotFound`→404, `UsernameTaken`/`GroupNameTaken`→409, `InvalidUsername`/`GroupNotFound`→422, `PermissionDenied`→403, `WeakPasswordError`→422 `weak_password`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_admin_api.py`:
```python
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import Role
from tests.factories import bearer, login, make_group, make_user

NEW_PASSWORD = "initial-pass-123"


async def _admin_token(client: AsyncClient, session: AsyncSession) -> str:
    await make_user(session, username="admin1", role=Role.ADMIN)
    return await login(client, "admin1")


async def test_regular_user_cannot_access_admin_api(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="plain")
    token = await login(client, "plain")
    response = await client.get("/api/admin/users", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


async def test_admin_with_pending_password_change_is_blocked(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="admin1", role=Role.ADMIN, must_change_password=True)
    token = await login(client, "admin1")
    response = await client.get("/api/admin/users", headers=bearer(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "password_change_required"


async def test_admin_creates_user_who_must_change_password(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin_token(client, session)
    group = await make_group(session, "hr")
    response = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={
            "username": "Worker",
            "full_name": "Worker One",
            "password": NEW_PASSWORD,
            "group_ids": [str(group.id)],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "worker"
    assert body["role"] == "user"
    assert body["must_change_password"] is True
    assert [g["name"] for g in body["groups"]] == ["hr"]

    login_response = await client.post(
        "/api/auth/login", json={"username": "worker", "password": NEW_PASSWORD}
    )
    assert login_response.json()["must_change_password"] is True


async def test_create_user_errors(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    base = {"username": "worker", "full_name": "W", "password": NEW_PASSWORD}

    weak = await client.post(
        "/api/admin/users", headers=bearer(token), json={**base, "password": "short"}
    )
    assert weak.status_code == 422
    assert weak.json()["detail"]["code"] == "weak_password"

    first = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert first.status_code == 201
    duplicate = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "username_taken"

    bad_group = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={**base, "username": "other", "group_ids": [str(uuid.uuid4())]},
    )
    assert bad_group.status_code == 422
    assert bad_group.json()["detail"]["code"] == "group_not_found"


async def test_admin_cannot_promote_user_to_admin_via_api(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin_token(client, session)
    plain = await make_user(session, username="plain")
    response = await client.patch(
        f"/api/admin/users/{plain.id}", headers=bearer(token), json={"role": "admin"}
    )
    assert response.status_code == 403
    create_admin = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={"username": "sneaky", "full_name": "S", "password": NEW_PASSWORD, "role": "admin"},
    )
    assert create_admin.status_code == 403


async def test_super_admin_promotes_user(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    token = await login(client, "root")
    plain = await make_user(session, username="plain")
    response = await client.patch(
        f"/api/admin/users/{plain.id}", headers=bearer(token), json={"role": "admin"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_suspended_user_token_is_rejected_immediately(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin_token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    target_token = await login(client, "target")
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 200

    suspend = await client.post(
        f"/api/admin/users/{target.id}/suspend", headers=bearer(admin_token)
    )
    assert suspend.status_code == 200
    assert suspend.json()["is_active"] is False
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 401

    reactivate = await client.post(
        f"/api/admin/users/{target.id}/reactivate", headers=bearer(admin_token)
    )
    assert reactivate.json()["is_active"] is True


async def test_unlock_and_reset_password(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    for _ in range(3):
        await client.post("/api/auth/login", json={"username": "target", "password": "nope"})

    unlock = await client.post(f"/api/admin/users/{target.id}/unlock", headers=bearer(token))
    assert unlock.status_code == 200
    assert unlock.json()["locked_until"] is None

    reset = await client.post(
        f"/api/admin/users/{target.id}/reset-password",
        headers=bearer(token),
        json={"new_password": "temporary-pass-11"},
    )
    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True
    login_response = await client.post(
        "/api/auth/login", json={"username": "target", "password": "temporary-pass-11"}
    )
    assert login_response.status_code == 200


async def test_unknown_user_is_404(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    response = await client.post(f"/api/admin/users/{uuid.uuid4()}/suspend", headers=bearer(token))
    assert response.status_code == 404


async def test_groups_crud(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    created = await client.post(
        "/api/admin/groups", headers=bearer(token), json={"name": "Finance", "description": "$"}
    )
    assert created.status_code == 201
    group_id = created.json()["id"]

    duplicate = await client.post(
        "/api/admin/groups", headers=bearer(token), json={"name": "Finance"}
    )
    assert duplicate.status_code == 409

    renamed = await client.patch(
        f"/api/admin/groups/{group_id}", headers=bearer(token), json={"name": "Accounting"}
    )
    assert renamed.json()["name"] == "Accounting"

    listed = await client.get("/api/admin/groups", headers=bearer(token))
    assert [g["name"] for g in listed.json()] == ["Accounting"]


async def test_audit_log_lists_admin_actions_with_request_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin_token(client, session)
    await client.post(
        "/api/admin/groups",
        headers={**bearer(token), "X-Request-ID": "trace-me-1"},
        json={"name": "Legal"},
    )
    response = await client.get(
        "/api/admin/audit", headers=bearer(token), params={"action": "group.created"}
    )
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["actor_username"] == "admin1"
    assert entries[0]["request_id"] == "trace-me-1"
    assert entries[0]["detail"] == {"name": "Legal"}


async def test_list_users(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    await make_user(session, username="zed")
    response = await client.get("/api/admin/users", headers=bearer(token))
    assert [u["username"] for u in response.json()] == ["admin1", "zed"]
```

Append to `backend/tests/test_route_protection.py`. Add `require_admin, require_super_admin` to the existing `app.auth.deps` import:
```python
def test_every_admin_route_requires_admin_role() -> None:
    role_guards = {require_admin, require_super_admin}
    missing = [
        f"{method} {route.path}"
        for route in _api_routes()
        if route.path.startswith("/api/admin")
        for method in sorted(route.methods)
        if not role_guards & set(_all_calls(route.dependant))
    ]
    assert missing == []
```

Run: `cd backend && uv run pytest tests/test_admin_api.py -v`
Expected: FAIL (404 responses, because the admin routes don't exist yet)

- [ ] **Step 2: Implement the admin routers**

`backend/app/api/admin_users.py`:
```python
import uuid

from fastapi import APIRouter, HTTPException

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.core.security import WeakPasswordError
from app.users import service
from app.users.schemas import (
    GroupCreate,
    GroupOut,
    GroupUpdate,
    PasswordReset,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_STATUS: dict[type[service.UserServiceError], int] = {
    service.NotFound: 404,
    service.UsernameTaken: 409,
    service.GroupNameTaken: 409,
    service.InvalidUsername: 422,
    service.GroupNotFound: 422,
    service.PermissionDenied: 403,
}


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WeakPasswordError):
        return api_error(422, "weak_password", str(exc))
    if isinstance(exc, service.UserServiceError):
        return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)
    raise exc


@router.get("/users")
async def list_users(_: AdminUser, session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await service.list_users(session)]


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, admin: AdminUser, session: SessionDep) -> UserOut:
    try:
        user = await service.create_user(
            session,
            actor=admin,
            username=body.username,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
            group_ids=body.group_ids,
        )
    except (service.UserServiceError, WeakPasswordError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.update_user(
            session,
            actor=admin,
            user_id=user_id,
            full_name=body.full_name,
            role=body.role,
            group_ids=body.group_ids,
        )
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


async def _set_active(
    user_id: uuid.UUID, active: bool, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.set_active(session, actor=admin, user_id=user_id, active=active)
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> UserOut:
    return await _set_active(user_id, False, admin, session)


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(user_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> UserOut:
    return await _set_active(user_id, True, admin, session)


@router.post("/users/{user_id}/unlock")
async def unlock_user(user_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> UserOut:
    try:
        user = await service.unlock_user(session, actor=admin, user_id=user_id)
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID, body: PasswordReset, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.reset_password(
            session, actor=admin, user_id=user_id, new_password=body.new_password
        )
    except (service.UserServiceError, WeakPasswordError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.get("/groups")
async def list_groups(_: AdminUser, session: SessionDep) -> list[GroupOut]:
    return [GroupOut.model_validate(g) for g in await service.list_groups(session)]


@router.post("/groups", status_code=201)
async def create_group(body: GroupCreate, admin: AdminUser, session: SessionDep) -> GroupOut:
    try:
        group = await service.create_group(
            session, actor=admin, name=body.name, description=body.description
        )
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return GroupOut.model_validate(group)


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: uuid.UUID, body: GroupUpdate, admin: AdminUser, session: SessionDep
) -> GroupOut:
    try:
        group = await service.update_group(
            session,
            actor=admin,
            group_id=group_id,
            name=body.name,
            description=body.description,
        )
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return GroupOut.model_validate(group)
```

`backend/app/api/admin_audit.py`:
```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.audit import service as audit
from app.audit.schemas import AuditEntryOut
from app.auth.deps import AdminUser, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit")
async def list_audit_entries(
    _: AdminUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_id: uuid.UUID | None = None,
) -> list[AuditEntryOut]:
    entries = await audit.list_entries(
        session, limit=limit, before_id=before_id, action=action, actor_id=actor_id
    )
    return [AuditEntryOut.model_validate(e) for e in entries]
```

Replace `backend/app/api/router.py` with:
```python
from fastapi import APIRouter

from app.api import admin_audit, admin_users, auth, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(admin_audit.router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_admin_api.py tests/test_route_protection.py -v`
Expected: all passed

- [ ] **Step 4: Lint, full suite, commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`
Expected: no lint errors; all tests pass

```bash
git add backend
git commit -m "feat(admin): add admin API for users, groups and audit log"
```

---

### Task 10: `create-superadmin` CLI

**Files:**
- Create: `backend/app/cli.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `create_user`, `UserServiceError` (Task 6); `WeakPasswordError` (Task 4); `get_settings` (Task 1); `create_engine`, `create_sessionmaker` (Task 2)
- Produces:
  - `app.cli.create_superadmin(sessionmaker: async_sessionmaker[AsyncSession], *, username: str, full_name: str, password: str) -> User`, which commits and sets `must_change_password=False`
  - `app.cli.main(argv: list[str] | None = None) -> int`. Usage: `python -m app.cli create-superadmin --username NAME --full-name "Full Name"`. The password comes from `RAG_SUPERADMIN_PASSWORD` or an interactive double prompt. Exit code 0 on success, 1 on error.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_cli.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.audit import service as audit
from app.core.config import get_settings
from app.core.db import create_sessionmaker
from app.core.security import verify_password


async def test_create_superadmin(engine: AsyncEngine) -> None:
    sessionmaker = create_sessionmaker(engine)
    user = await cli.create_superadmin(
        sessionmaker, username="Root", full_name="Root Admin", password="root-password-123"
    )
    assert user.username == "root"
    assert user.role == "super_admin"
    assert user.must_change_password is False
    assert verify_password(user.password_hash, "root-password-123")

    async with sessionmaker() as session:
        entry = (await audit.list_entries(session))[0]
    assert entry.action == "user.created"
    assert entry.actor_id is None


def test_main_rejects_weak_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RAG_SUPERADMIN_PASSWORD", "short")
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    get_settings.cache_clear()
    try:
        code = cli.main(["create-superadmin", "--username", "root", "--full-name", "Root"])
    finally:
        get_settings.cache_clear()
    assert code == 1
    assert "at least 12" in capsys.readouterr().err


def test_main_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])
```

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'cli' from 'app'`

- [ ] **Step 2: Implement the CLI**

`backend/app/cli.py`:
```python
"""Operator commands. Usage: python -m app.cli create-superadmin --username NAME --full-name NAME"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.security import WeakPasswordError
from app.users.models import Role, User
from app.users.service import UserServiceError, create_user


async def create_superadmin(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    username: str,
    full_name: str,
    password: str,
) -> User:
    async with sessionmaker() as session:
        user = await create_user(
            session,
            actor=None,
            username=username,
            full_name=full_name,
            password=password,
            role=Role.SUPER_ADMIN,
            must_change_password=False,
        )
        await session.commit()
        return user


def _read_password() -> str:
    from_env = os.environ.get("RAG_SUPERADMIN_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise WeakPasswordError("Passwords do not match")
    return first


async def _run_create_superadmin(username: str, full_name: str, password: str) -> User:
    engine = create_engine(get_settings().database_url)
    try:
        return await create_superadmin(
            create_sessionmaker(engine), username=username, full_name=full_name, password=password
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="Create the first super admin")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    args = parser.parse_args(argv)

    try:
        user = asyncio.run(
            _run_create_superadmin(args.username, args.full_name, _read_password())
        )
    except (UserServiceError, WeakPasswordError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created super admin '{user.username}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: 3 passed

- [ ] **Step 4: Lint and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app`

```bash
git add backend
git commit -m "feat(cli): add create-superadmin command"
```

---

### Task 11: Docker image, Compose stack, Makefile and CI

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `deploy/docker-compose.yml`, `deploy/.env.example`, `Makefile`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: everything above; `create_app` factory; Alembic migrations; `app.cli`
- Produces: `docker compose -f deploy/docker-compose.yml up -d --build` starts `postgres` and `api` (bound to `127.0.0.1:8000`) with health checks. The API runs migrations on start. CI runs lint, type check, tests and the image build on every push.

- [ ] **Step 1: Write the Docker files**

`backend/.dockerignore`:
```
.venv
.mypy_cache
.ruff_cache
.pytest_cache
__pycache__
tests
*.pyc
```

`backend/Dockerfile`:
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12.11-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

FROM python:3.12.11-slim-bookworm
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers"]
```

- [ ] **Step 2: Write the Compose stack and env template**

`deploy/.env.example`:
```bash
# Copy to deploy/.env and fill in. Never commit deploy/.env.

RAG_ENV=prod
RAG_LOG_LEVEL=INFO

# Database. Use only letters and digits in the password (it is embedded in a URL).
POSTGRES_USER=rag
POSTGRES_PASSWORD=change-me-letters-and-digits-only
POSTGRES_DB=rag

# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
RAG_JWT_SECRET=

# Set to false only for local HTTP testing; production runs behind HTTPS.
RAG_COOKIE_SECURE=true
# JSON list of browser origins allowed to call the API, e.g. ["https://rag.example.com"]
RAG_CORS_ORIGINS=[]
```

`deploy/docker-compose.yml`:
```yaml
name: multimodal-rag

services:
  postgres:
    image: postgres:17.6-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:?set POSTGRES_USER in deploy/.env}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in deploy/.env}
      POSTGRES_DB: ${POSTGRES_DB:?set POSTGRES_DB in deploy/.env}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10

  api:
    build:
      context: ../backend
    restart: unless-stopped
    env_file: .env
    environment:
      RAG_DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s

volumes:
  postgres-data:
```

- [ ] **Step 3: Write the Makefile**

`Makefile` (recipe lines must be indented with a **tab**):
```make
COMPOSE = docker compose -f deploy/docker-compose.yml

.PHONY: up down logs test lint create-superadmin

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

# Usage: make create-superadmin USERNAME=root FULL_NAME="Root Admin"
create-superadmin:
	$(COMPOSE) exec api python -m app.cli create-superadmin --username $(USERNAME) --full-name "$(FULL_NAME)"
```

On Windows without `make`, run the commands after each target name directly.

- [ ] **Step 4: Write the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy app
      - run: uv run pytest

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build backend
```

- [ ] **Step 5: Verify the stack end to end**

```bash
cp deploy/.env.example deploy/.env
# Edit deploy/.env: set POSTGRES_PASSWORD to letters+digits, set RAG_JWT_SECRET to the output of:
python -c "import secrets; print(secrets.token_urlsafe(48))"
# For this local HTTP check also set RAG_COOKIE_SECURE=false

docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```
Expected: `postgres` and `api` both show `healthy` (wait up to ~30 s).

```bash
curl -s http://127.0.0.1:8000/api/health
```
Expected: `{"status":"ok","database":"ok"}`

```bash
docker compose -f deploy/docker-compose.yml exec -e RAG_SUPERADMIN_PASSWORD=root-password-123 api python -m app.cli create-superadmin --username root --full-name "Root Admin"
curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"root","password":"root-password-123"}'
```
Expected: `Created super admin 'root'`, then a JSON body containing `"access_token"` and `"role":"super_admin"`.

```bash
docker compose -f deploy/docker-compose.yml logs api | tail -n 5
```
Expected: JSON log lines with `"event": "http_request"` and a `request_id`.

```bash
docker compose -f deploy/docker-compose.yml exec api whoami
```
Expected: `appuser` (not root)

Clean up the local data when finished: `docker compose -f deploy/docker-compose.yml down -v`

- [ ] **Step 6: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore deploy/docker-compose.yml deploy/.env.example Makefile .github/workflows/ci.yml
git commit -m "build: add docker image, compose stack, makefile and CI"
```

---

## Spec coverage for this plan

| Spec requirement | Task |
|---|---|
| §2.2 `core` (settings, DB, logging, request IDs) | 1, 2, 3 |
| §2.2 `auth` (login, JWT, password hashing, role checks, lockout) | 4, 7, 8 |
| §2.2 `users` (users, groups, suspension) | 4, 6, 9 |
| §2.2 `audit` append-only | 5 |
| §5.3 role checks on every route; login lockout; ORM-only SQL; Pydantic validation | 7, 8, 9 |
| §6.2 roles and permissions per role | 6, 9 |
| §6.3 admin-created users, forced first-login change, Argon2, JWT + httpOnly refresh, revoke on suspension/role change, `make create-superadmin` | 6, 7, 8, 10, 11 |
| §6.9 audit log fields | 5, 9 |
| §7.2 structured JSON logs with request ID; `/health` | 3 |
| §8.2 install steps; auto migrations | 11 |
| §8.3 multi-stage, non-root, pinned, health checks | 11 |
| §9 unit + integration (testcontainers) + route-auth security test + CI | 2–11 |

Deferred to later plans by design: strikes (Plan 4), sessions revoked on group change (not needed until collections exist, Plan 2), CSRF beyond SameSite=Strict + bearer tokens (the frontend in Plan 6 sends the access token as a header, which browsers never attach automatically), CSV audit export (Plan 7).
