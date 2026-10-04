# Plan 1 — Backend Foundation & Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A secure FastAPI backend running in Docker. An admin creates users and groups, users log in, roles are enforced on every route, and important actions are written to an append-only audit log.

**Architecture:** One Python package `app` under `backend/`, split into small modules (`core`, `users`, `audit`, `auth`, `api`). Service functions take an `AsyncSession` and never commit; API routes and the CLI commit. Routers are thin and turn service errors into HTTP errors with the body `{"detail": {"code": ..., "message": ...}}`. Authentication uses one signed JWT access token (8 hours) sent as `Authorization: Bearer`.

**Tech Stack:** Python 3.12, uv, FastAPI, Uvicorn, Pydantic v2 + pydantic-settings, SQLAlchemy 2 (async) + asyncpg, Alembic, argon2-cffi, PyJWT, pytest + pytest-asyncio + httpx + testcontainers, ruff, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md`

## Where this plan fits

The v1 spec is delivered as a series of plans. Each plan produces working, tested software, and each later plan is written just before it is executed:

1. **Backend foundation & identity** (this plan)
2. **Documents & ingestion:** collections, access groups, uploads, MinIO, Redis + Celery, ClamAV, Gotenberg, Docling, enrichment, chunking, embeddings, Qdrant (spec §3, §6.1). *Check that the chosen MinIO image is still published; if not, use another S3-compatible store.*
3. **Retrieval & answering:** LLM gateway, RagConfig, hybrid search, rerank, SSE chat, citations, feedback, Phoenix tracing, **request-ID middleware + JSON logs** (spec §4, §7.2)
4. **Guardrails & abuse protection**, including strikes (spec §5)
5. **Evaluation & review queue** (spec §7.1)
6. **Frontend foundation + user app** (spec §6.4, §6.8)
7. **Admin console**, including audit filters, paging and CSV export (spec §6.5)
8. **Production packaging:** Caddy, backup/restore, Playwright E2E, **GitHub Actions CI, Makefile, strict mypy, migration-drift test** (spec §8, §9)

## Global Constraints

- Python **3.12** (`requires-python = ">=3.12,<3.13"`); dependencies managed with **uv**; `uv.lock` committed.
- Environment variables use the prefix **`RAG_`**; `RAG_JWT_SECRET` is required and must be ≥ 32 characters.
- Roles are exactly `user`, `admin`, `super_admin`. `admin` manages only `user` accounts; `super_admin` manages everyone (spec §6.2).
- **Admins create users directly**; new users **must change their password at first login**. No email, no self-registration (spec §6.3).
- Argon2 password hashing; one JWT access token valid **8 hours**; tokens are revoked immediately on suspension, role change, password change or admin password reset (spec §6.3).
- Login lockout after **5 failed attempts for 15 minutes** (spec §5.3).
- The audit log is **append-only** and stores actor, action, target, details (JSON) and timestamp (spec §6.9).
- Every API route except the public allowlist requires authentication, enforced by an automated test (spec §9).
- Docker image: multi-stage, **non-root**, pinned versions, health checks; migrations run automatically on API start (spec §8).
- Service functions never call `commit()`; routes and the CLI do.

## Review Focus

1. **Username typed with different case or spaces** (`" Alice "` vs `alice`): treated as the same account. Tests in Task 3 (`test_username_is_normalized_and_unique`) and Task 4 (`test_login_is_case_and_space_insensitive`).
2. **Suspended user still holding a valid token:** the next request is rejected with 401. Test in Task 5 (`test_deactivated_user_token_is_rejected_immediately`).
3. **Password change:** the token issued before the change stops working. Test in Task 4 (`test_forced_password_change_flow`).
4. **Correct password while locked, then after the lock expires:** rejected during the lock, accepted after it. Test in Task 4 (`test_lock_blocks_correct_password_until_expiry`).
5. **Admin privilege escalation:** an `admin` cannot create or promote `admin`/`super_admin` accounts, and nobody can change their own role or deactivate themselves. Tests in Task 3 and Task 5 (`test_admin_cannot_promote_to_admin`).

---

## File structure (end state of this plan)

```
.gitattributes
.gitignore
deploy/
  docker-compose.yml               # postgres + api (later plans add services)
  .env.example
backend/
  .python-version                  # 3.12
  pyproject.toml
  uv.lock
  Dockerfile
  .dockerignore
  alembic.ini
  migrations/
    env.py
    script.py.mako
    versions/0001_identity_and_audit.py
  app/
    __init__.py
    main.py                        # create_app() factory
    models.py                      # imports every ORM model
    cli.py                         # python -m app.cli create-superadmin
    core/
      __init__.py
      config.py                    # Settings, get_settings, get_app_settings
      db.py                        # Base, engine, sessionmaker, get_session
      security.py                  # Argon2, password strength
    users/
      __init__.py
      models.py                    # Role, User, Group, user_groups
      schemas.py
      service.py
    audit/
      __init__.py
      models.py                    # AuditLog
      schemas.py
      service.py                   # record(), list_recent()
    auth/
      __init__.py
      tokens.py
      service.py                   # authenticate, change_password
      deps.py                      # current_user, require_admin, ...
    api/
      __init__.py
      errors.py
      router.py
      health.py
      auth.py
      admin.py
  tests/
    __init__.py
    conftest.py
    factories.py
    test_foundation.py
    test_models.py
    test_users_service.py
    test_auth.py
    test_admin_api.py
    test_cli.py
```

All commands run from the repository root unless a step says `cd backend`. **Docker Desktop must be running** for the tests (testcontainers starts Postgres).

---

### Task 1: Project scaffold, settings, database and health check

**Files:**
- Create: `.gitattributes`, `.gitignore`, `backend/.python-version`, `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/models.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/.gitkeep`, `backend/app/api/__init__.py`, `backend/app/api/errors.py`, `backend/app/api/health.py`, `backend/app/api/router.py`, `backend/app/main.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_foundation.py`

**Interfaces:**
- Produces:
  - `app.core.config.Settings` (fields: `env: Literal["dev","test","prod"]`, `database_url: str`, `jwt_secret: SecretStr`, `jwt_ttl_seconds: int = 28800`, `login_max_failed_attempts: int = 5`, `login_lockout_seconds: int = 900`), `get_settings() -> Settings` (cached), `get_app_settings(request) -> Settings`
  - `app.core.db`: `Base`, `create_engine(url) -> AsyncEngine`, `create_sessionmaker(engine) -> async_sessionmaker[AsyncSession]` (`expire_on_commit=False`), `get_session(request) -> AsyncIterator[AsyncSession]`
  - `app.api.errors.api_error(status_code, code, message, headers=None, **extra) -> HTTPException`
  - `app.api.router.api_router` (prefix `/api`)
  - `app.main.create_app(settings: Settings | None = None) -> FastAPI`, which sets `app.state.settings`, `app.state.engine` and `app.state.sessionmaker`
  - `GET /api/health` → 200 `{"status": "ok", "database": "ok"}` or 503 `{"status": "degraded", "database": "error"}`
  - Test fixtures: `postgres_url` (session-scoped, migrated), `settings`, `engine` (truncates all tables after each test), `session`, `app`, `client`

- [ ] **Step 1: Create repo files and the uv project**

`.gitattributes`:
```
* text=auto eol=lf
*.png binary
*.jpg binary
*.pdf binary
```

`.gitignore`:
```
__pycache__/
*.py[cod]
.venv/
.ruff_cache/
.pytest_cache/
node_modules/
.next/
.env
deploy/.env
*.log
.DS_Store
Thumbs.db
.idea/
.vscode/
```

```bash
mkdir -p backend/app/core backend/app/api backend/tests backend/migrations/versions
cd backend
uv init --bare --name multimodal-rag-backend --python 3.12
uv python pin 3.12
uv add fastapi "uvicorn[standard]" pydantic-settings "sqlalchemy[asyncio]" asyncpg alembic argon2-cffi pyjwt
uv add --dev pytest pytest-asyncio httpx "testcontainers[postgres]" ruff
```

Edit `backend/pyproject.toml`: set `requires-python = ">=3.12,<3.13"`, keep the dependency lists `uv add` wrote, and append:
```toml
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
```
Run `uv sync`. Create empty files: `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/api/__init__.py`, `backend/tests/__init__.py`, `backend/migrations/versions/.gitkeep`.

- [ ] **Step 2: Write the settings and database modules**

`backend/app/core/config.py`:
```python
from functools import lru_cache
from typing import Literal, cast

from fastapi import Request
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field maps to an env var with the RAG_ prefix."""

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    jwt_secret: SecretStr
    jwt_ttl_seconds: int = 8 * 60 * 60
    login_max_failed_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

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
    return create_async_engine(url, pool_pre_ping=True)


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

- [ ] **Step 3: Write the Alembic configuration**

`backend/alembic.ini`:
```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

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


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


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

- [ ] **Step 4: Write the API error helper, health route, router and app factory**

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

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
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
    app.include_router(api_router)
    return app
```

- [ ] **Step 5: Write the shared test fixtures**

`backend/tests/conftest.py`:
```python
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

# Must be set before app modules read settings.
os.environ.setdefault("RAG_JWT_SECRET", "test-only-secret-" + "x" * 32)

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.postgres import PostgresContainer

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


@pytest.fixture
def settings(postgres_url: str) -> Settings:
    return Settings(_env_file=None, env="test", database_url=postgres_url, login_max_failed_attempts=3)


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
```

- [ ] **Step 6: Write the tests**

`backend/tests/test_foundation.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app


def test_settings_read_prefixed_env_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_JWT_SECRET", "s" * 40)
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"
    assert settings.jwt_ttl_seconds == 8 * 60 * 60
    assert settings.login_max_failed_attempts == 5
    assert settings.login_lockout_seconds == 900


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None, jwt_secret="short")


async def test_database_session_works(session: AsyncSession) -> None:
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


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
```

- [ ] **Step 7: Run tests and lint**

Run: `cd backend && uv run pytest -v`
Expected: 5 passed. A Docker connection error means Docker Desktop isn't running.

Run: `cd backend && uv run ruff check . && uv run ruff format --check .`
Expected: no errors (run `uv run ruff format .` first if the format check fails)

- [ ] **Step 8: Commit**

```bash
git add .gitattributes .gitignore backend
git commit -m "feat(backend): scaffold project with settings, database, alembic and health check"
```

---

### Task 2: Identity and audit data model

**Files:**
- Create: `backend/app/core/security.py`, `backend/app/users/__init__.py`, `backend/app/users/models.py`, `backend/app/audit/__init__.py`, `backend/app/audit/models.py`, `backend/app/audit/service.py`, `backend/migrations/versions/0001_identity_and_audit.py`, `backend/tests/factories.py`
- Modify: `backend/app/models.py`
- Delete: `backend/migrations/versions/.gitkeep`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `Base` (Task 1)
- Produces:
  - `app.core.security`: `hash_password(password) -> str`, `verify_password(password_hash, password) -> bool`, `validate_password_strength(password) -> None` (raises `WeakPasswordError(ValueError)`; rules: 12–128 characters with at least one letter and one digit)
  - `app.users.models`: `Role(StrEnum)` (`USER`, `ADMIN`, `SUPER_ADMIN`), `ROLE_RANK: dict[Role, int]`, `Group` (`id`, `name`, `description`, `created_at`), `User` (`id`, `username`, `full_name`, `password_hash`, `role: str`, `is_active`, `must_change_password`, `failed_login_count`, `locked_until`, `token_version`, `created_at`, `groups: list[Group]`)
  - `app.audit.models.AuditLog` (`id: int`, `created_at`, `actor_id`, `actor_username`, `action`, `target_type`, `target_id`, `detail: dict`)
  - `app.audit.service.record(session, *, action, actor=None, target_type=None, target_id=None, detail=None) -> AuditLog` (flushes, never commits); `list_recent(session, limit=100) -> list[AuditLog]` (newest first)
  - `tests/factories.py`: `DEFAULT_PASSWORD`, `make_user(session, *, username="alice", role=Role.USER, password=DEFAULT_PASSWORD, must_change_password=False, is_active=True, groups=()) -> User`, `make_group(session, name="engineering") -> Group`

- [ ] **Step 1: Write the failing tests**

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

`backend/tests/test_models.py`:
```python
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.audit.models import AuditLog
from app.core.security import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.users.models import Group, User
from tests.factories import make_user


def test_password_hash_roundtrip() -> None:
    password_hash = hash_password("correct-horse-42")
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct-horse-42")
    assert not verify_password(password_hash, "wrong-horse-42")
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("password", "message"),
    [("short1", "at least 12"), ("a" * 12, "letter and a digit"), ("a1" * 65, "at most 128")],
)
def test_weak_passwords_are_rejected(password: str, message: str) -> None:
    with pytest.raises(WeakPasswordError, match=message):
        validate_password_strength(password)


async def test_user_defaults_and_groups(session: AsyncSession) -> None:
    session.add(
        User(username="bob", full_name="Bob", password_hash="x", role="user", groups=[Group(name="hr")])
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
    assert loaded.created_at is not None
    assert [g.name for g in loaded.groups] == ["hr"]


async def test_invalid_role_is_rejected_by_database(session: AsyncSession) -> None:
    session.add(User(username="eve", full_name="Eve", password_hash="x", role="root"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_audit_record_and_list(session: AsyncSession) -> None:
    actor = await make_user(session, username="carol")
    await audit.record(session, action="first")
    entry = await audit.record(
        session, action="second", actor=actor, target_type="user", target_id=actor.id, detail={"k": 1}
    )
    await session.commit()

    assert entry.actor_username == "carol"
    assert entry.target_id == str(actor.id)
    assert [e.action for e in await audit.list_recent(session)] == ["second", "first"]


async def test_audit_log_is_append_only(session: AsyncSession) -> None:
    entry = await audit.record(session, action="event")
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(AuditLog).where(AuditLog.id == entry.id).values(action="x"))
    await session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(AuditLog).where(AuditLog.id == entry.id))
    await session.rollback()
```

Run: `cd backend && uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.security'`

- [ ] **Step 2: Implement password security**

`backend/app/core/security.py`:
```python
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


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
    if len(password) < 12:
        raise WeakPasswordError("Password must be at least 12 characters")
    if len(password) > 128:
        raise WeakPasswordError("Password must be at most 128 characters")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise WeakPasswordError("Password must contain at least one letter and a digit")
```

- [ ] **Step 3: Implement the models and audit service**

`backend/app/users/__init__.py` and `backend/app/audit/__init__.py`: empty files.

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
    # Incremented to revoke every token issued before it (deactivation, role/password change).
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    groups: Mapped[list[Group]] = relationship(secondary=user_groups, lazy="selectin")
```

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
    """Append-only: a database trigger rejects UPDATE and DELETE (migration 0001).
    actor_id has no foreign key on purpose, so audit rows outlive any user change."""

    __tablename__ = "audit_log"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[uuid.UUID | None]
    actor_username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
```

`backend/app/audit/service.py`:
```python
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog

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
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_recent(session: AsyncSession, limit: int = 100) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())
```

Replace `backend/app/models.py` with:
```python
"""Import every ORM model so Base.metadata knows all tables (used by Alembic and tests)."""

from app.audit.models import AuditLog
from app.users.models import Group, User, user_groups

__all__ = ["AuditLog", "Group", "User", "user_groups"]
```

- [ ] **Step 4: Write the migration**

Delete `backend/migrations/versions/.gitkeep`, then create `backend/migrations/versions/0001_identity_and_audit.py`:
```python
"""users, groups and append-only audit log

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin', 'super_admin')", name=op.f("ck_users_role_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_user_groups_group_id_groups"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_groups_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id", name=op.f("pk_user_groups")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
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
    op.drop_table("audit_log")
    op.drop_table("user_groups")
    op.drop_table("users")
    op.drop_table("groups")
```

Note: `TRUNCATE` (used by the test fixtures) does not fire row-level triggers, by design.

- [ ] **Step 5: Run tests and lint**

Run: `cd backend && uv run pytest -v`
Expected: all passed

Run: `cd backend && uv run ruff format . && uv run ruff check .`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(identity): add users, groups, argon2 passwords and append-only audit log"
```

---

### Task 3: User and group management service

**Files:**
- Create: `backend/app/users/service.py`
- Test: `backend/tests/test_users_service.py`

**Interfaces:**
- Consumes: `User`, `Group`, `Role` (Task 2); `hash_password`, `validate_password_strength`, `WeakPasswordError` (Task 2); `audit.record` (Task 2)
- Produces (all in `app.users.service`; none commit):
  - Errors: `UserServiceError(Exception)` with `.code` and `.message`; subclasses `NotFound` (`"not_found"`), `UsernameTaken` (`"username_taken"`), `InvalidUsername` (`"invalid_username"`), `GroupNotFound` (`"group_not_found"`), `GroupNameTaken` (`"group_name_taken"`), `PermissionDenied` (`"forbidden"`)
  - `create_user(session, *, actor: User | None, username, full_name, password, role=Role.USER, group_ids=(), must_change_password=True) -> User`. `actor=None` means the system (CLI).
  - `update_user(session, *, actor: User, user_id, full_name=None, role=None, group_ids=None, is_active=None, unlock=False) -> User`
  - `reset_password(session, *, actor: User, user_id, new_password) -> User`
  - `list_users(session) -> list[User]`, `create_group(session, *, actor, name, description="") -> Group`, `list_groups(session) -> list[Group]`
  - Audit actions: `user.created`, `user.updated`, `user.password_reset`, `group.created`

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


async def test_create_user(session: AsyncSession) -> None:
    group = await make_group(session, "hr")
    user = await users.create_user(
        session, actor=None, username="new.person", full_name=" New Person ",
        password=STRONG, group_ids=[group.id],
    )
    await session.commit()
    assert user.full_name == "New Person"
    assert user.role == "user"
    assert user.must_change_password is True
    assert verify_password(user.password_hash, STRONG)
    assert [g.name for g in user.groups] == ["hr"]
    entry = (await audit.list_recent(session))[0]
    assert entry.action == "user.created"
    assert "password" not in str(entry.detail)


async def test_username_is_normalized_and_unique(session: AsyncSession) -> None:
    user = await users.create_user(
        session, actor=None, username="  Alice ", full_name="A", password=STRONG
    )
    assert user.username == "alice"
    with pytest.raises(users.UsernameTaken):
        await users.create_user(session, actor=None, username="ALICE", full_name="B", password=STRONG)


@pytest.mark.parametrize("bad", ["ab", "has space", "x" * 65, "semi;colon"])
async def test_invalid_usernames_rejected(session: AsyncSession, bad: str) -> None:
    with pytest.raises(users.InvalidUsername):
        await users.create_user(session, actor=None, username=bad, full_name="X", password=STRONG)


async def test_weak_password_and_unknown_group_rejected(session: AsyncSession) -> None:
    with pytest.raises(WeakPasswordError):
        await users.create_user(session, actor=None, username="weak", full_name="W", password="short")
    with pytest.raises(users.GroupNotFound):
        await users.create_user(
            session, actor=None, username="nogroup", full_name="N",
            password=STRONG, group_ids=[uuid.uuid4()],
        )


async def test_role_rules_for_creating_users(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    plain = await make_user(session, username="plain")

    assert (await users.create_user(
        session, actor=admin, username="worker", full_name="W", password=STRONG
    )).role == "user"
    with pytest.raises(users.PermissionDenied):
        await users.create_user(
            session, actor=admin, username="admin2", full_name="A", password=STRONG, role=Role.ADMIN
        )
    with pytest.raises(users.PermissionDenied):
        await users.create_user(session, actor=plain, username="other", full_name="O", password=STRONG)
    assert (await users.create_user(
        session, actor=root, username="admin3", full_name="A", password=STRONG, role=Role.ADMIN
    )).role == "admin"


async def test_update_role_and_groups(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    eng = await make_group(session, "eng")
    target = await make_user(session, username="target")
    updated = await users.update_user(
        session, actor=root, user_id=target.id, role=Role.ADMIN, group_ids=[eng.id]
    )
    assert updated.role == "admin"
    assert updated.token_version == 1
    assert [g.name for g in updated.groups] == ["eng"]


async def test_admin_cannot_edit_admins_or_promote(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    other_admin = await make_user(session, username="admin2", role=Role.ADMIN)
    plain = await make_user(session, username="plain")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=other_admin.id, full_name="X")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=plain.id, role=Role.ADMIN)


async def test_cannot_change_own_role_or_deactivate_self(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    with pytest.raises(users.PermissionDenied, match="own role"):
        await users.update_user(session, actor=root, user_id=root.id, role=Role.USER)
    with pytest.raises(users.PermissionDenied, match="yourself"):
        await users.update_user(session, actor=root, user_id=root.id, is_active=False)


async def test_deactivate_revokes_tokens_and_unlock_clears_lock(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    target.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    target.failed_login_count = 2
    await session.commit()

    updated = await users.update_user(
        session, actor=admin, user_id=target.id, is_active=False, unlock=True
    )
    assert updated.is_active is False
    assert updated.token_version == 1
    assert updated.locked_until is None
    assert updated.failed_login_count == 0


async def test_update_unknown_user(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    with pytest.raises(users.NotFound):
        await users.update_user(session, actor=admin, user_id=uuid.uuid4(), full_name="X")


async def test_reset_password_forces_change_and_revokes(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    reset = await users.reset_password(
        session, actor=admin, user_id=target.id, new_password="temporary-pass-11"
    )
    assert verify_password(reset.password_hash, "temporary-pass-11")
    assert reset.must_change_password is True
    assert reset.token_version == 1


async def test_groups(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    group = await users.create_group(session, actor=admin, name=" Finance ", description="money")
    assert group.name == "Finance"
    with pytest.raises(users.GroupNameTaken):
        await users.create_group(session, actor=admin, name="Finance")
    assert [g.name for g in await users.list_groups(session)] == ["Finance"]
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


def _normalize_username(raw: str) -> str:
    username = raw.strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise InvalidUsername(
            "Username must be 3-64 characters using letters, digits, '.', '_' or '-'"
        )
    return username


def _ensure_can_manage(actor: User | None, target_role: Role) -> None:
    """super_admin manages everyone; admin manages only regular users; None is the system."""
    if actor is None or actor.role == Role.SUPER_ADMIN:
        return
    if actor.role == Role.ADMIN and target_role is Role.USER:
        return
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
    normalized = _normalize_username(username)
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
        detail={"username": normalized, "role": role.value},
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
    is_active: bool | None = None,
    unlock: bool = False,
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
    if is_active is not None and is_active != user.is_active:
        if not is_active and user.id == actor.id:
            raise PermissionDenied("You cannot deactivate yourself")
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
        changes["is_active"] = is_active
    if unlock:
        user.locked_until = None
        user.failed_login_count = 0
        changes["unlocked"] = True

    await session.flush()
    await audit.record(
        session, action="user.updated", actor=actor, target_type="user", target_id=user.id,
        detail=changes,
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
        session, action="user.password_reset", actor=actor, target_type="user", target_id=user.id
    )
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def create_group(
    session: AsyncSession, *, actor: User | None, name: str, description: str = ""
) -> Group:
    clean_name = name.strip()
    if await session.scalar(select(Group.id).where(Group.name == clean_name)) is not None:
        raise GroupNameTaken(f"Group '{clean_name}' already exists")
    group = Group(name=clean_name, description=description.strip())
    session.add(group)
    await session.flush()
    await audit.record(
        session, action="group.created", actor=actor, target_type="group", target_id=group.id,
        detail={"name": clean_name},
    )
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.scalars(select(Group).order_by(Group.name))).all())
```

- [ ] **Step 3: Run tests and lint**

Run: `cd backend && uv run pytest tests/test_users_service.py -v`
Expected: all passed

Run: `cd backend && uv run ruff format . && uv run ruff check .`

- [ ] **Step 4: Commit**

```bash
git add backend
git commit -m "feat(users): add user and group management with role rules"
```

---

### Task 4: Authentication (login, lockout, password change, route guard)

**Files:**
- Create: `backend/app/auth/__init__.py`, `backend/app/auth/tokens.py`, `backend/app/auth/service.py`, `backend/app/auth/deps.py`, `backend/app/users/schemas.py`, `backend/app/api/auth.py`
- Modify: `backend/app/api/router.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `Settings`, `get_app_settings` (Task 1); `get_session`, `api_error` (Task 1); `User`, `Role`, `ROLE_RANK` (Task 2); security helpers and `audit.record` (Task 2)
- Produces:
  - `app.auth.tokens`: `TokenError(Exception)`; `create_access_token(user: User, settings: Settings, now: datetime | None = None) -> str`; `decode_access_token(token: str, settings: Settings) -> tuple[UUID, int]` (user ID, token version)
  - `app.auth.service`: `AuthError` with `.code`; `InvalidCredentials` (`"invalid_credentials"`), `AccountLocked` (`"account_locked"`, `.until`), `AccountDisabled` (`"account_disabled"`); `authenticate(session, *, username, password, settings, now=None) -> User` (records failures **before raising**, so callers commit on failure too); `change_password(session, *, user, current_password, new_password) -> User`
  - `app.auth.deps`: `SessionDep`, `SettingsDep`, `current_user_allow_password_change`, `current_user` (403 `password_change_required` while a change is pending), `require_admin`, `require_super_admin`, aliases `CurrentUser`, `AdminUser`
  - `app.users.schemas`: `GroupOut`, `UserOut`, `UserCreate`, `UserUpdate`, `PasswordReset`, `GroupCreate`
  - Endpoints: `POST /api/auth/login` and `POST /api/auth/change-password` → `TokenResponse {access_token, token_type: "bearer", expires_in, must_change_password, user}`; `GET /api/auth/me` → `UserOut`
  - Error codes: 401 `not_authenticated` / `invalid_token` / `invalid_credentials`; 423 `account_locked`; 403 `account_disabled` / `password_change_required` / `forbidden`; 400 `invalid_credentials` (wrong current password); 422 `weak_password`
  - Audit actions: `auth.login_succeeded`, `auth.login_failed`, `auth.account_locked`, `auth.password_changed`
  - `tests/factories.py` gains `login(client, username, password=DEFAULT_PASSWORD) -> str` and `bearer(token) -> dict`
  - `PUBLIC_ROUTES` allowlist in `tests/test_auth.py`

- [ ] **Step 1: Add the test helpers**

Append to `backend/tests/factories.py`. Add `from httpx import AsyncClient` to its imports:
```python
async def login(client: AsyncClient, username: str, password: str = DEFAULT_PASSWORD) -> str:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_auth.py`:
```python
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth import service as auth
from app.auth.deps import current_user_allow_password_change, require_admin, require_super_admin
from app.auth.tokens import TokenError, create_access_token, decode_access_token
from app.core.config import Settings
from app.main import create_app
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

# Routes reachable without a token. Adding one must be a deliberate, reviewed decision.
PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}


# ---------- tokens ----------

def test_token_roundtrip_and_rejections(settings: Settings) -> None:
    import uuid

    from app.users.models import User

    user = User(id=uuid.uuid4(), username="u", role="user", token_version=3)
    assert decode_access_token(create_access_token(user, settings), settings) == (user.id, 3)

    expired = create_access_token(user, settings, now=datetime.now(UTC) - timedelta(hours=9))
    with pytest.raises(TokenError):
        decode_access_token(expired, settings)
    other = Settings(_env_file=None, jwt_secret="z" * 40)
    with pytest.raises(TokenError):
        decode_access_token(create_access_token(user, other), settings)
    with pytest.raises(TokenError):
        decode_access_token("not.a.jwt", settings)


# ---------- authenticate() ----------

async def test_login_is_case_and_space_insensitive(session: AsyncSession, settings: Settings) -> None:
    await make_user(session, username="alice")
    user = await auth.authenticate(session, username="  Alice ", password=DEFAULT_PASSWORD, settings=settings)
    assert user.username == "alice"
    assert (await audit.list_recent(session))[0].action == "auth.login_succeeded"


async def test_wrong_password_locks_after_max_attempts(session: AsyncSession, settings: Settings) -> None:
    # settings fixture: login_max_failed_attempts=3, lockout 900 s
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for _ in range(2):
        with pytest.raises(auth.InvalidCredentials):
            await auth.authenticate(session, username="alice", password="wrong", settings=settings, now=now)
    with pytest.raises(auth.AccountLocked) as locked:
        await auth.authenticate(session, username="alice", password="wrong", settings=settings, now=now)
    assert locked.value.until == now + timedelta(seconds=900)
    assert user.failed_login_count == 0


async def test_lock_blocks_correct_password_until_expiry(session: AsyncSession, settings: Settings) -> None:
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    user.locked_until = now + timedelta(minutes=15)
    await session.commit()
    with pytest.raises(auth.AccountLocked):
        await auth.authenticate(session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=now)
    later = now + timedelta(minutes=15, seconds=1)
    result = await auth.authenticate(session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=later)
    assert result.locked_until is None


async def test_unknown_and_disabled_users(session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(auth.InvalidCredentials):
        await auth.authenticate(session, username="ghost", password="x", settings=settings)
    await make_user(session, username="off", is_active=False)
    with pytest.raises(auth.InvalidCredentials):  # wrong password doesn't reveal "disabled"
        await auth.authenticate(session, username="off", password="wrong", settings=settings)
    with pytest.raises(auth.AccountDisabled):
        await auth.authenticate(session, username="off", password=DEFAULT_PASSWORD, settings=settings)


# ---------- HTTP API ----------

async def test_login_api(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    ok = await client.post("/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD})
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 60 * 60
    assert body["user"]["username"] == "alice"
    assert "password_hash" not in body["user"]

    bad = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "invalid_credentials"


async def test_failed_logins_are_persisted_and_lock(client: AsyncClient, session: AsyncSession) -> None:
    user = await make_user(session, username="alice")
    for _ in range(2):
        await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    locked = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"
    await session.refresh(user)
    assert user.locked_until is not None


async def test_me_requires_valid_token(client: AsyncClient, session: AsyncSession) -> None:
    assert (await client.get("/api/auth/me")).json()["detail"]["code"] == "not_authenticated"
    assert (await client.get("/api/auth/me", headers=bearer("garbage"))).status_code == 401
    await make_user(session, username="alice")
    me = await client.get("/api/auth/me", headers=bearer(await login(client, "alice")))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_forced_password_change_flow(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="newbie", must_change_password=True)
    first = await client.post("/api/auth/login", json={"username": "newbie", "password": DEFAULT_PASSWORD})
    assert first.json()["must_change_password"] is True
    token = first.json()["access_token"]

    # /me works so the frontend can show the change-password screen
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 200

    wrong = await client.post(
        "/api/auth/change-password", headers=bearer(token),
        json={"current_password": "wrong", "new_password": "fresh-secret-99"},
    )
    assert wrong.status_code == 400
    weak = await client.post(
        "/api/auth/change-password", headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert weak.json()["detail"]["code"] == "weak_password"

    changed = await client.post(
        "/api/auth/change-password", headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "fresh-secret-99"},
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False
    # the old token is revoked; the new one works
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer(changed.json()["access_token"]))).status_code == 200


# ---------- route guard ----------

def _all_calls(dependant: Dependant) -> Iterator[Callable[..., Any] | None]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _all_calls(dependency)


def _api_routes() -> list[APIRoute]:
    app = create_app(
        Settings(_env_file=None, jwt_secret="x" * 40, database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x")
    )
    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_every_non_public_route_requires_authentication() -> None:
    routes = _api_routes()
    unprotected = [
        f"{method} {route.path}"
        for route in routes
        for method in sorted(route.methods)
        if (method, route.path) not in PUBLIC_ROUTES
        and current_user_allow_password_change not in set(_all_calls(route.dependant))
    ]
    assert unprotected == []
    assert PUBLIC_ROUTES <= {(m, r.path) for r in routes for m in r.methods}


def test_every_admin_route_requires_admin_role() -> None:
    guards = {require_admin, require_super_admin}
    missing = [
        f"{method} {route.path}"
        for route in _api_routes()
        if route.path.startswith("/api/admin")
        for method in sorted(route.methods)
        if not guards & set(_all_calls(route.dependant))
    ]
    assert missing == []
```

Run: `cd backend && uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Implement tokens and the auth service**

`backend/app/auth/__init__.py`: empty file.

`backend/app/auth/tokens.py`:
```python
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.users.models import User

_ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def create_access_token(user: User, settings: Settings, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "tv": user.token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> tuple[uuid.UUID, int]:
    """Returns (user_id, token_version). Raises TokenError for any invalid token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
        return uuid.UUID(str(payload["sub"])), int(payload["tv"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc
```

`backend/app/auth/service.py`:
```python
"""Login and password change. Functions never commit.
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

# Checked when the username doesn't exist, so response time doesn't reveal that.
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


async def _failed(session: AsyncSession, user: User | None, reason: str, username: str) -> None:
    await audit.record(
        session,
        action="auth.login_failed",
        actor=user,
        target_type="user" if user else None,
        target_id=user.id if user else None,
        detail={"reason": reason, "username": username[:64]},
    )


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
        await _failed(session, None, "unknown_user", normalized)
        raise InvalidCredentials()

    if user.locked_until is not None and user.locked_until > now:
        await _failed(session, user, "locked", normalized)
        raise AccountLocked(user.locked_until)

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        await _failed(session, user, "bad_password", normalized)
        if user.failed_login_count >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            user.failed_login_count = 0
            await audit.record(
                session, action="auth.account_locked", actor=user, target_type="user",
                target_id=user.id,
            )
            raise AccountLocked(user.locked_until)
        raise InvalidCredentials()

    if not user.is_active:
        await _failed(session, user, "disabled", normalized)
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

- [ ] **Step 4: Implement schemas, dependencies and the auth router**

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
    is_active: bool | None = None
    unlock: bool = False


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
```

`backend/app/auth/deps.py`:
```python
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.auth.tokens import TokenError, decode_access_token
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
        user_id, token_version = decode_access_token(credentials.credentials, settings)
    except TokenError:
        raise api_error(401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH) from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise api_error(401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH)
    return user


async def current_user(
    user: Annotated[User, Depends(current_user_allow_password_change)],
) -> User:
    if user.must_change_password:
        raise api_error(403, "password_change_required", "You must change your password first")
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
```

`backend/app/api/auth.py`:
```python
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
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
from app.auth.tokens import create_access_token
from app.core.config import Settings
from app.core.security import WeakPasswordError
from app.users.models import User
from app.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

PendingUser = Annotated[User, Depends(current_user_allow_password_change)]


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


def _token_response(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user, settings),
        expires_in=settings.jwt_ttl_seconds,
        must_change_password=user.must_change_password,
        user=UserOut.model_validate(user),
    )


@router.post("/login")
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    try:
        user = await authenticate(
            session, username=body.username, password=body.password, settings=settings
        )
    except AccountLocked as exc:
        await session.commit()  # persist the lock and the audit entries
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
    return _token_response(user, settings)


@router.get("/me")
async def me(user: PendingUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password")
async def change_password_route(
    body: ChangePasswordRequest, user: PendingUser, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    try:
        await change_password(
            session, user=user, current_password=body.current_password,
            new_password=body.new_password,
        )
    except InvalidCredentials as exc:
        raise api_error(400, exc.code, "Current password is incorrect") from None
    except WeakPasswordError as exc:
        raise api_error(422, "weak_password", str(exc)) from None
    await session.commit()
    return _token_response(user, settings)
```

Replace `backend/app/api/router.py` with:
```python
from fastapi import APIRouter

from app.api import auth, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
```

- [ ] **Step 5: Run tests and lint**

Run: `cd backend && uv run pytest -v`
Expected: all passed

Run: `cd backend && uv run ruff format . && uv run ruff check .`

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(auth): add login with lockout, forced password change and route guard"
```

---

### Task 5: Admin API for users, groups and the audit log

**Files:**
- Create: `backend/app/api/admin.py`, `backend/app/audit/schemas.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_admin_api.py`

**Interfaces:**
- Consumes: `app.users.service` (Task 3); schemas, `AdminUser`, `SessionDep` (Task 4); `audit.list_recent` (Task 2); `api_error` (Task 1); `WeakPasswordError` (Task 2)
- Produces endpoints (all require `admin` or higher):
  - `GET /api/admin/users` → `list[UserOut]`
  - `POST /api/admin/users` (201) body `UserCreate` → `UserOut`
  - `PATCH /api/admin/users/{user_id}` body `UserUpdate` (`full_name`, `role`, `group_ids`, `is_active`, `unlock`) → `UserOut`
  - `POST /api/admin/users/{user_id}/reset-password` body `PasswordReset` → `UserOut`
  - `GET /api/admin/groups` → `list[GroupOut]`; `POST /api/admin/groups` (201) body `GroupCreate` → `GroupOut`
  - `GET /api/admin/audit?limit=100` → `list[AuditEntryOut]`, newest first
  - Error mapping: `NotFound`→404, `UsernameTaken`/`GroupNameTaken`→409, `InvalidUsername`/`GroupNotFound`→422, `PermissionDenied`→403, `WeakPasswordError`→422 `weak_password`

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


async def test_non_admins_are_blocked(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="plain")
    response = await client.get("/api/admin/users", headers=bearer(await login(client, "plain")))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"

    await make_user(session, username="admin9", role=Role.ADMIN, must_change_password=True)
    pending = await client.get("/api/admin/users", headers=bearer(await login(client, "admin9")))
    assert pending.json()["detail"]["code"] == "password_change_required"


async def test_admin_creates_user_who_must_change_password(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin_token(client, session)
    group = await make_group(session, "hr")
    created = await client.post(
        "/api/admin/users", headers=bearer(token),
        json={"username": "Worker", "full_name": "Worker One", "password": NEW_PASSWORD,
              "group_ids": [str(group.id)]},
    )
    assert created.status_code == 201
    assert created.json()["username"] == "worker"
    assert created.json()["must_change_password"] is True
    assert [g["name"] for g in created.json()["groups"]] == ["hr"]

    first_login = await client.post("/api/auth/login", json={"username": "worker", "password": NEW_PASSWORD})
    assert first_login.json()["must_change_password"] is True

    listed = await client.get("/api/admin/users", headers=bearer(token))
    assert [u["username"] for u in listed.json()] == ["admin1", "worker"]


async def test_create_user_errors(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    base = {"username": "worker", "full_name": "W", "password": NEW_PASSWORD}
    weak = await client.post("/api/admin/users", headers=bearer(token), json={**base, "password": "short"})
    assert weak.json()["detail"]["code"] == "weak_password"
    first = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert first.status_code == 201
    duplicate = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert duplicate.status_code == 409
    bad_group = await client.post(
        "/api/admin/users", headers=bearer(token),
        json={**base, "username": "other", "group_ids": [str(uuid.uuid4())]},
    )
    assert bad_group.json()["detail"]["code"] == "group_not_found"


async def test_admin_cannot_promote_to_admin(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    plain = await make_user(session, username="plain")
    promote = await client.patch(f"/api/admin/users/{plain.id}", headers=bearer(token), json={"role": "admin"})
    assert promote.status_code == 403
    create_admin = await client.post(
        "/api/admin/users", headers=bearer(token),
        json={"username": "sneaky", "full_name": "S", "password": NEW_PASSWORD, "role": "admin"},
    )
    assert create_admin.status_code == 403


async def test_super_admin_promotes_user(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    plain = await make_user(session, username="plain")
    response = await client.patch(
        f"/api/admin/users/{plain.id}", headers=bearer(await login(client, "root")), json={"role": "admin"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_deactivated_user_token_is_rejected_immediately(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin_token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    target_token = await login(client, "target")
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 200

    off = await client.patch(
        f"/api/admin/users/{target.id}", headers=bearer(admin_token), json={"is_active": False}
    )
    assert off.json()["is_active"] is False
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 401


async def test_unlock_and_reset_password(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    for _ in range(3):
        await client.post("/api/auth/login", json={"username": "target", "password": "nope"})

    unlocked = await client.patch(f"/api/admin/users/{target.id}", headers=bearer(token), json={"unlock": True})
    assert unlocked.json()["locked_until"] is None

    reset = await client.post(
        f"/api/admin/users/{target.id}/reset-password", headers=bearer(token),
        json={"new_password": "temporary-pass-11"},
    )
    assert reset.json()["must_change_password"] is True
    relogin = await client.post("/api/auth/login", json={"username": "target", "password": "temporary-pass-11"})
    assert relogin.status_code == 200

    missing = await client.patch(f"/api/admin/users/{uuid.uuid4()}", headers=bearer(token), json={"unlock": True})
    assert missing.status_code == 404


async def test_groups_and_audit(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    created = await client.post("/api/admin/groups", headers=bearer(token), json={"name": "Legal"})
    assert created.status_code == 201
    duplicate = await client.post("/api/admin/groups", headers=bearer(token), json={"name": "Legal"})
    assert duplicate.status_code == 409
    groups = await client.get("/api/admin/groups", headers=bearer(token))
    assert [g["name"] for g in groups.json()] == ["Legal"]

    entries = (await client.get("/api/admin/audit", headers=bearer(token))).json()
    assert entries[0]["action"] == "group.created"
    assert entries[0]["actor_username"] == "admin1"
    assert entries[0]["detail"] == {"name": "Legal"}
```

Run: `cd backend && uv run pytest tests/test_admin_api.py -v`
Expected: FAIL (404 responses, because the admin routes don't exist yet)

- [ ] **Step 2: Implement the audit schema and admin router**

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
```

`backend/app/api/admin.py`:
```python
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.errors import api_error
from app.audit import service as audit
from app.audit.schemas import AuditEntryOut
from app.auth.deps import AdminUser, SessionDep
from app.core.security import WeakPasswordError
from app.users import service
from app.users.schemas import (
    GroupCreate,
    GroupOut,
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


def _http_error(exc: service.UserServiceError | WeakPasswordError) -> HTTPException:
    if isinstance(exc, WeakPasswordError):
        return api_error(422, "weak_password", str(exc))
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


@router.get("/users")
async def list_users(_: AdminUser, session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await service.list_users(session)]


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, admin: AdminUser, session: SessionDep) -> UserOut:
    try:
        user = await service.create_user(
            session, actor=admin, username=body.username, full_name=body.full_name,
            password=body.password, role=body.role, group_ids=body.group_ids,
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
            session, actor=admin, user_id=user_id, full_name=body.full_name, role=body.role,
            group_ids=body.group_ids, is_active=body.is_active, unlock=body.unlock,
        )
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


@router.get("/audit")
async def list_audit(
    _: AdminUser, session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[AuditEntryOut]:
    return [AuditEntryOut.model_validate(e) for e in await audit.list_recent(session, limit)]
```

Replace `backend/app/api/router.py` with:
```python
from fastapi import APIRouter

from app.api import admin, auth, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
```

- [ ] **Step 3: Run the full suite and lint**

Run: `cd backend && uv run pytest -v`
Expected: all passed, including both route-guard tests in `test_auth.py`

Run: `cd backend && uv run ruff format . && uv run ruff check .`

- [ ] **Step 4: Commit**

```bash
git add backend
git commit -m "feat(admin): add admin API for users, groups and audit log"
```

---

### Task 6: `create-superadmin` CLI, Docker image and Compose stack

**Files:**
- Create: `backend/app/cli.py`, `backend/Dockerfile`, `backend/.dockerignore`, `deploy/docker-compose.yml`, `deploy/.env.example`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `create_user`, `UserServiceError` (Task 3); `WeakPasswordError` (Task 2); `get_settings` (Task 1); `create_engine`, `create_sessionmaker` (Task 1)
- Produces:
  - `app.cli.create_superadmin(sessionmaker, *, username, full_name, password) -> User`, which commits and sets `must_change_password=False`
  - `app.cli.main(argv=None) -> int`. Usage: `python -m app.cli create-superadmin --username NAME --full-name "Full Name"`. The password comes from `RAG_SUPERADMIN_PASSWORD` or an interactive double prompt. Exit code 0 on success, 1 on error.
  - `docker compose -f deploy/docker-compose.yml up -d --build` starts `postgres` + `api` (on `127.0.0.1:8000`) with health checks; migrations run on API start

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_cli.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.core.config import get_settings
from app.core.db import create_sessionmaker
from app.core.security import verify_password


async def test_create_superadmin(engine: AsyncEngine) -> None:
    user = await cli.create_superadmin(
        create_sessionmaker(engine), username="Root", full_name="Root Admin",
        password="root-password-123",
    )
    assert user.username == "root"
    assert user.role == "super_admin"
    assert user.must_change_password is False
    assert verify_password(user.password_hash, "root-password-123")


def test_main_rejects_weak_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The password is validated before any database access.
    monkeypatch.setenv("RAG_SUPERADMIN_PASSWORD", "short")
    monkeypatch.setenv("RAG_DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    get_settings.cache_clear()
    try:
        code = cli.main(["create-superadmin", "--username", "root", "--full-name", "Root"])
    finally:
        get_settings.cache_clear()
    assert code == 1
    assert "at least 12" in capsys.readouterr().err
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
    sessionmaker: async_sessionmaker[AsyncSession], *, username: str, full_name: str, password: str
) -> User:
    async with sessionmaker() as session:
        user = await create_user(
            session, actor=None, username=username, full_name=full_name, password=password,
            role=Role.SUPER_ADMIN, must_change_password=False,
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


async def _run(username: str, full_name: str, password: str) -> User:
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
        user = asyncio.run(_run(args.username, args.full_name, _read_password()))
    except (UserServiceError, WeakPasswordError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created super admin '{user.username}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `cd backend && uv run pytest -v && uv run ruff format . && uv run ruff check .`
Expected: all tests pass; no lint errors

- [ ] **Step 3: Write the Docker files**

`backend/.dockerignore`:
```
.venv
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

`deploy/.env.example`:
```bash
# Copy to deploy/.env and fill in. Never commit deploy/.env.
RAG_ENV=prod

# Use only letters and digits in the password (it is embedded in a URL).
POSTGRES_USER=rag
POSTGRES_PASSWORD=changeMeLettersAndDigits1
POSTGRES_DB=rag

# Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"
RAG_JWT_SECRET=
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

- [ ] **Step 4: Verify the stack end to end**

```bash
cp deploy/.env.example deploy/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste the output as RAG_JWT_SECRET in deploy/.env

docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```
Expected: `postgres` and `api` both `healthy` (wait up to ~30 s).

```bash
curl -s http://127.0.0.1:8000/api/health
```
Expected: `{"status":"ok","database":"ok"}`

```bash
docker compose -f deploy/docker-compose.yml exec -e RAG_SUPERADMIN_PASSWORD=root-password-123 api python -m app.cli create-superadmin --username root --full-name "Root Admin"
curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"root","password":"root-password-123"}'
docker compose -f deploy/docker-compose.yml exec api whoami
```
Expected: `Created super admin 'root'`; a JSON body containing `"access_token"` and `"role":"super_admin"`; `appuser`.

Clean up: `docker compose -f deploy/docker-compose.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add backend deploy
git commit -m "build: add create-superadmin CLI, docker image and compose stack"
```

---

## Spec coverage for this plan

| Spec requirement | Task |
|---|---|
| §2.2 `core`, `users`, `audit`, `auth` modules | 1–4 |
| §5.3 role checks on every route, login lockout, Pydantic validation, ORM-only SQL | 4, 5 |
| §6.2 roles and what each can do | 3, 5 |
| §6.3 admin-created users, forced first-login change, Argon2, 8-hour JWT, immediate revocation, `create-superadmin` | 2, 3, 4, 6 |
| §6.9 append-only audit log | 2, 5 |
| §7.2 `/health` | 1 |
| §8.2 install steps, automatic migrations; §8.3 multi-stage, non-root, pinned, health checks | 6 |
| §9 unit + integration (testcontainers) + route-auth security test | 1–6 |

Postponed by design: request-ID middleware and JSON logs (Plan 3), strikes (Plan 4), audit filters/paging/CSV and group editing (Plan 7), CI, Makefile, strict mypy and migration-drift test (Plan 8).
