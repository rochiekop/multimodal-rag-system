# Plan 8 — Production Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the product into something a company installs and runs on its own server, as spec §8 describes:
- `cp deploy/.env.example deploy/.env`, set secrets, `docker compose up -d`, `make create-superadmin`;
- HTTPS through Caddy, with security headers;
- one-command backup and restore;
- CI on every push.

**Architecture:**
- **Caddy is the only service with host ports.**
  - It serves HTTPS (automatic certificates for `RAG_DOMAIN`, or plain HTTP when `RAG_DOMAIN=:80`).
  - It routes `/api/*` straight to FastAPI (streaming flushed, never compressed) and `/phoenix*` to Phoenix behind basic auth. Everything else goes to a new Next.js `frontend` container (standalone output, non-root).
- **Backend hardening:**
  - Stale eval runs are reaped.
  - Every response, including unhandled 500s, carries the request ID.
  - Access logs are JSON.
  - Ingestion tasks get a hard time limit, and workers are recycled.
- **Ops scripts** (`scripts/*.sh`, wrapped by a `Makefile`) back up and restore Postgres, Qdrant and the files volume.
- **CI:** a GitHub Actions workflow runs ruff, mypy, pytest, the frontend checks and both image builds. A migration-drift test keeps the models and Alembic in step.

**Tech Stack:** Docker Compose, Caddy 2.10, Node 24 (alpine) for the frontend image, the existing Python 3.12 / uv backend image, GNU Make + bash, GitHub Actions (`astral-sh/setup-uv`, `actions/setup-node`, `docker/build-push-action`), mypy (+ the pydantic plugin), Alembic autogenerate comparison.

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md`:
- §8 (repository layout, install/upgrade, production details);
- §9 (CI line);
- §1.2 success criterion 6 (fresh install);
- §5.3 (web security, CORS/CSRF, httpOnly cookies);
- §7.2 (structured logs with request IDs, health checks).

## Decisions this plan relies on (made with the user, 2026-10-08)

- **Phoenix** is served at `https://<domain>/phoenix` behind Caddy basic auth: one shared ops user, with the bcrypt hash in `deploy/.env`. The admin console's trace links point there (`NEXT_PUBLIC_PHOENIX_URL=/phoenix`).
- **CI** runs checks and image builds only. The Playwright e2e stays a documented manual step: it needs a seeded stack and a real OpenAI key.

## Rulings made while planning

- **Caddy is the only exposed service.**
  - `api` and `phoenix` lose their host ports in `deploy/docker-compose.yml`.
  - A new `deploy/docker-compose.dev.yml` override adds `127.0.0.1:8000` (api) and `127.0.0.1:6006` (phoenix) back for local development with `npm run dev`.
  - Cost if wrong: developers must pass `-f docker-compose.dev.yml`, and the README says so.
- **HTTPS modes, chosen with `RAG_DOMAIN` in `deploy/.env`:**
  - a public DNS name (automatic Let's Encrypt);
  - `localhost` or an intranet name (Caddy's internal CA, so browsers warn until it is trusted);
  - `:80` (plain HTTP, which needs `RAG_SESSION_COOKIE_SECURE=false`, documented).
  - Host ports are `${HTTP_PORT:-80}` and `${HTTPS_PORT:-443}`, so a verification stack can run alongside the dev stack.
- **CSP:** `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`.
  - Next.js App Router injects inline bootstrap scripts. Nonces would force every page to render dynamically, so we accept `'unsafe-inline'` for scripts. Markdown is already sanitized and images are rendered as links.
  - The CSP is applied to the app and the API, not to `/phoenix` (Phoenix ships its own UI).
  - Cost if wrong: a weaker XSS backstop than a nonce-based CSP.
- **Request IDs:** Caddy overwrites `X-Request-ID` with its own UUID, so a client can't plant IDs in audit rows (Plan 3 carry-in). The backend's middleware also turns unhandled exceptions into a JSON 500 that carries the ID, and logs one JSON access line per request. Uvicorn's own access log is turned off.
- **Body limits at Caddy:**
  - 500 MB on `POST /api/admin/collections/*/documents` (several files of at most 100 MB each);
  - 10 MB on the rest of `/api`.
  
  This closes the Plan 2 parked "disk-filling uploads" ruling.
- **Worker limits:**
  - The ingestion task gets `time_limit=3600` s (a hard kill). A killed version is recoverable with Retry after `STUCK_AFTER`.
  - Workers run with `--max-tasks-per-child=20` and a compose `mem_limit` (worker 6g, worker-eval 3g).
  
  This closes the Plan 2 parked "worker memory/time limits" ruling.
- **Stale eval runs:** a run still `running` 6 hours after `started_at` is marked failed ("Timed out: the evaluation worker stopped") whenever runs are listed or read. This is lazy and needs no scheduler (Plan 5 carry-in).
- **Phoenix:**
  - It gets its own database `phoenix` and role `phoenix`, created by a Postgres init script on fresh installs and by `make phoenix-db` on existing ones.
  - It serves under `PHOENIX_HOST_ROOT_PATH=/phoenix`.
  - Existing traces in the app database's `phoenix` schema are not migrated (dev data only).
- **The backend image keeps the model warmup after `COPY app`.** A BuildKit cache mount keeps the downloads across rebuilds (the Plan 2 parked "slow rebuilds" ruling). Cost if wrong: the models are still copied into the layer on each rebuild, but not re-downloaded.
- **mypy** runs on `backend/app` in default (non-strict) mode, with the pydantic plugin and `ignore_missing_imports` for libraries without type information. Every error it reports is fixed, not suppressed with blanket ignores.
- **Backups:**
  - A backup is a timestamped folder `backups/<UTC timestamp>/` holding `postgres.dump` (app database), `phoenix.dump`, `qdrant-<collection>.snapshot`, `files.tar.gz` and `manifest.txt`.
  - It never copies `deploy/.env`, which holds secrets. The script prints a reminder that `deploy/.env` (including `RAG_SECRETS_KEY`) must be backed up separately, because without it saved API keys are unreadable.
  - `restore` refuses to run without `--yes` or typing the folder name.
- **Verification uses a separate compose project** (`-p rag-verify`) with its own volumes and ports 8080/8443. The user's dev stack and its data are never touched. That project's volumes are removed at the end, and only that project's.

## Scope limits (deferred, by design)

- No Kubernetes, no image registry pushes, no automatic certificate renewal monitoring (Caddy handles renewal).
- No scheduled backups: `make backup` can be run from cron, as the README shows.
- Playwright e2e is not in CI (user decision); it is documented with a seeding global-setup.

## Global Constraints

- **Install (spec §8.2):**
  1. `cp deploy/.env.example deploy/.env` and set the domain, secrets and API keys.
  2. `docker compose up -d`. Migrations run automatically when the API starts.
  3. `make create-superadmin`.
  
  To upgrade: pull new images and run `docker compose up -d`; migrations apply automatically.
- **Production details (spec §8.3):**
  - Multi-stage images, non-root users, pinned versions, named volumes, and health checks with `depends_on: condition: service_healthy`.
  - `make backup` / `make restore`: a Postgres dump, a Qdrant snapshot and a copy of the files volume, in one timestamped folder.
- **CI (spec §9):** "ruff, mypy, eslint, all tests, Docker image builds on every push."
- **Web security (spec §5.3):** sanitized Markdown, CSRF protection, secure httpOnly cookies, strict CORS (none: same origin), Pydantic validation, ORM-only SQL, login lockout.
- **Pins:**
  - Pin every image to an exact version tag that exists on Docker Hub. Check with `docker pull <tag>` before writing it.
  - Keep `ragas==0.4.3`, `langchain-community==0.4.1` and the uv overrides (`jiter>=0.17.0`, `openai>=3.24.0,<4`).
- **Secrets:** never print or commit `deploy/.env`, `RAG_OPENAI_API_KEY`, `RAG_SECRETS_KEY`, `RAG_JWT_SECRET`, passwords or hashes. Example files hold placeholders only.
- **Your local data:** never run `docker compose down -v`, `docker volume rm` or `prune` against the default `multimodal-rag` project. Only the `rag-verify` project created in Task 7 may have its volumes removed.
- **Backend:** ruff (line length 100), mypy and the full pytest suite stay green.
- **Frontend:** `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` all pass.
- **Scripts:** bash with `set -euo pipefail`, runnable from Git Bash on Windows and from bash on Linux.

## Review Focus

1. **A streamed answer through Caddy** must arrive token by token, not all at once. Compression and buffering must never touch `text/event-stream`. Checked in Task 7 (`curl -N` through Caddy shows `event: token` lines arriving before `event: done`, with a timing comparison).
2. **An unhandled exception** must produce a JSON 500 that carries `x-request-id`, with the traceback logged as JSON under the same ID. Test in Task 1 (`test_unhandled_error_returns_json_500_with_request_id`).
3. **A client-supplied `X-Request-ID`** must be replaced by Caddy's own ID. Checked in Task 7 (send `X-Request-ID: forged` and see a different ID echoed).
4. **Restore after data loss** must bring back documents, their search index and the uploaded files, so a question cites them again. Checked in Task 7 (backup, delete the collection's document and run `make restore`; the answer still cites the PDF and the page image loads).
5. **A model and migrations out of step** (a column added to a model without an Alembic revision) must fail CI. Test in Task 2 (`test_models_match_migrations`).

---

## File structure (new or changed)

```
backend/
  app/evaluation/runs.py            # reap_stale_runs                                     (T1)
  app/api/admin_evaluation.py       # reap before list/get                                (T1)
  app/core/logging.py               # JSON 500 + access log in RequestIdMiddleware        (T1)
  app/ingestion/tasks.py            # task time_limit                                     (T1)
  Dockerfile                        # model cache mount, no uvicorn access log, forwarded-allow-ips (T1)
  tests/test_logging.py, tests/test_eval_runs.py                                          (T1)
  pyproject.toml, uv.lock           # mypy + config                                       (T2)
  app/**                            # type fixes found by mypy                            (T2)
  tests/test_migrations.py          # models vs migrations drift                          (T2)
frontend/
  next.config.ts                    # output: "standalone"                                (T3)
  Dockerfile, .dockerignore, README.md                                                    (T3)
  e2e/global-setup.ts, e2e/fixtures/leave-policy.pdf, playwright.config.ts                (T7)
deploy/
  Caddyfile                                                                                (T4)
  docker-compose.yml, docker-compose.dev.yml, .env.example                                 (T4)
  postgres-init/10-phoenix.sh                                                              (T4)
scripts/
  backup.sh, restore.sh, phoenix-db.sh                                                     (T5)
Makefile                                                                                   (T5)
.github/workflows/ci.yml                                                                   (T6)
README.md                                                                                  (T7)
docs/superpowers/plans/2026-10-08-plan-8-followups.md                                      (T7)
```

---

### Task 1: Backend runtime hardening

**Files:**
- Modify: `backend/app/evaluation/runs.py`, `backend/app/api/admin_evaluation.py`
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/ingestion/tasks.py`
- Modify: `backend/Dockerfile`
- Test: `backend/tests/test_eval_runs.py` (append), `backend/tests/test_logging.py` (append)

**Interfaces:**
- Consumes:
  - `EvalRun` (`status`, `started_at`, `error`, `finished_at`);
  - `request_id_var`;
  - `celery_app`.
- Produces:
  - `runs.RUN_TIMEOUT = timedelta(hours=6)`;
  - `async reap_stale_runs(session, now: datetime | None = None) -> int`, which returns how many runs it failed;
  - `RequestIdMiddleware` now always answers with the request ID, even on unhandled errors, and logs one `app.access` line per request with `method`, `path`, `status` and `duration_ms`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_eval_runs.py`. Reuse the file's existing helpers to create an eval set and case; look at how the existing tests in this file build an `EvalRun`, and follow the same pattern for the fields `EvalRun` requires.

```python
async def test_stale_running_runs_are_reaped(session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    from app.evaluation import runs
    from app.evaluation.models import EvalRun

    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    eval_set = await _make_set_with_case(session)  # use this file's existing helper/pattern
    stale = EvalRun(eval_set_id=eval_set.id, status="running", case_count=1, summary={},
                    config={}, started_at=now - timedelta(hours=7))
    fresh = EvalRun(eval_set_id=eval_set.id, status="running", case_count=1, summary={},
                    config={}, started_at=now - timedelta(hours=1))
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
```

If the file has no `_make_set_with_case` helper, write one at the top of the test using the same model constructors the file already uses. Also add any `EvalRun` columns the model requires (for example `created_by`).

Append to `backend/tests/test_logging.py`:

```python
async def test_unhandled_error_returns_json_500_with_request_id(app, caplog) -> None:
    from httpx import ASGITransport, AsyncClient

    @app.get("/api/boom-test")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        with caplog.at_level(logging.ERROR):
            response = await http.get("/api/boom-test", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-500"
    assert response.json() == {
        "detail": {
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": "req-500",
        }
    }
    assert "kaboom" in caplog.text


async def test_access_log_line_per_request(client: AsyncClient, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.access"):
        await client.get("/api/health", headers={"X-Request-ID": "req-log"})
    records = [r for r in caplog.records if r.name == "app.access"]
    assert len(records) == 1
    record = records[0]
    assert (record.method, record.path, record.status) == ("GET", "/api/health", 200)
    assert record.duration_ms >= 0
```

Run: `cd backend && uv run pytest tests/test_eval_runs.py tests/test_logging.py -q`
Expected: FAIL. `reap_stale_runs` is missing, the 500 test gets no request ID, and there are no `app.access` records.

- [ ] **Step 2: Reap stale runs**

In `backend/app/evaluation/runs.py`, next to the other constants:

```python
RUN_TIMEOUT = timedelta(hours=6)
TIMED_OUT = "Timed out: the evaluation worker stopped"
```

and the function:

```python
async def reap_stale_runs(session: AsyncSession, now: datetime | None = None) -> int:
    """Fail runs stuck in `running` past RUN_TIMEOUT. Runs are acked early, so a worker that
    died mid-run would otherwise leave them running forever. Flushes; the caller commits."""
    now = now or datetime.now(UTC)
    result = await session.execute(
        update(EvalRun)
        .where(EvalRun.status == "running", EvalRun.started_at < now - RUN_TIMEOUT)
        .values(status="failed", error=TIMED_OUT, finished_at=now)
    )
    return result.rowcount or 0
```

(Import `timedelta` if it isn't imported yet.)

In `backend/app/api/admin_evaluation.py`, call it at the start of `list_runs` and `get_run`, then commit:

```python
    if await runs.reap_stale_runs(session):
        await session.commit()
```

- [ ] **Step 3: JSON 500 and access log in the middleware**

Replace `RequestIdMiddleware.__call__` in `backend/app/core/logging.py` with:

```python
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
        request_id = incoming if _VALID_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                message["headers"] = [*message.get("headers", []), (HEADER, request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("Unhandled error")
            if response_started:
                raise  # too late to send a response; the server closes the connection
            body = json.dumps(
                {
                    "detail": {
                        "code": "internal_error",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                }
            ).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            access_logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)
```

At module level add `import json`, `import time`, `logger = logging.getLogger(__name__)` and `access_logger = logging.getLogger("app.access")`.

The access log is written in `finally` before the request ID is reset, so the line carries it.

`main.py` adds this middleware with `add_middleware`, which places it *inside* Starlette's `ServerErrorMiddleware`. Exceptions from routes therefore reach it first, and the JSON 500 is sent before Starlette's plain-text one. Check this with the test.

In `configure_logging`, keep the uvicorn error logger flowing through the JSON root handler:

```python
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
```

`uvicorn.access` is turned off in the Dockerfile (Step 5); the middleware's `app.access` line replaces it.

- [ ] **Step 4: Ingestion time limit and worker recycling**

In `backend/app/ingestion/tasks.py`, change the task decorator to:

```python
@celery_app.task(
    bind=True, name="ingestion.ingest_version", max_retries=MAX_RETRIES, time_limit=3600
)
```

Add a comment above it: `# A hard limit kills a runaway parse; the version stays in its stage and Retry recovers it after STUCK_AFTER.`

Worker recycling (`--max-tasks-per-child`) is set on the compose command lines in Task 4.

- [ ] **Step 5: Dockerfile**

In `backend/Dockerfile`, final stage:

1. Replace `RUN python -m app.ingestion.warmup` with a cache-mounted warmup that copies the models into the image:

```dockerfile
# Model downloads are cached across rebuilds (BuildKit), then copied into the image layer.
RUN --mount=type=cache,target=/tmp/model-cache,uid=10001,gid=10001 \
    HF_HOME=/tmp/model-cache/huggingface \
    FASTEMBED_CACHE_PATH=/tmp/model-cache/fastembed \
    TIKTOKEN_CACHE_DIR=/tmp/model-cache/tiktoken \
    python -m app.ingestion.warmup \
    && cp -a /tmp/model-cache/. /app/.cache/
```

2. Change `CMD` to:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
```

`--forwarded-allow-ips='*'` is safe because only Caddy can reach the API (Task 4 removes its host port).

Build the image to check it: `docker build -t rag-backend:check backend`. Expected: success, with `models ready` printed during the build. Then run `docker run --rm rag-backend:check python -c "import app.main"`, which must succeed.

The app reads `HF_HOME`, `FASTEMBED_CACHE_PATH` and `TIKTOKEN_CACHE_DIR` from the image's `ENV` (`/app/.cache/...`) at runtime. So the copied models must end up exactly under `/app/.cache/huggingface`, `/app/.cache/fastembed` and `/app/.cache/tiktoken`. The `cp -a /tmp/model-cache/. /app/.cache/` above preserves those subfolder names. Confirm by running the image offline: `docker run --rm --network none rag-backend:check python -m app.ingestion.warmup` must succeed without network.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/evaluation/runs.py backend/app/api/admin_evaluation.py backend/app/core/logging.py backend/app/ingestion/tasks.py backend/Dockerfile backend/tests/test_eval_runs.py backend/tests/test_logging.py
git commit -m "feat(backend): reap stale eval runs, json 500s and access logs with request ids, ingestion time limit"
```

---

### Task 2: mypy and the migration-drift test

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Modify: files under `backend/app/` that mypy flags
- Create: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `uv run mypy` passes on `app/`. Task 6's CI runs exactly `uv run mypy`.

- [ ] **Step 1: Add mypy**

Run (in `backend/`): `uv add --dev mypy`

Append to `backend/pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
files = ["app"]
plugins = ["pydantic.mypy"]
warn_unused_ignores = true
warn_redundant_casts = true
check_untyped_defs = true

[[tool.mypy.overrides]]
module = ["celery.*", "docling.*", "docling_core.*", "ragas.*", "fastembed.*", "phoenix.*", "openinference.*", "pythonjsonlogger.*"]
ignore_missing_imports = true
```

Check that the `openai` version (3.26.x) and `ragas==0.4.3` are unchanged after `uv add`.

- [ ] **Step 2: Fix every error**

Run: `uv run mypy`

Fix each reported error properly: correct annotations, `cast()` where a library returns `Any`, and narrowing with `isinstance` or `assert` for real invariants. Use `# type: ignore[code]` only for a genuine library typing bug, always with the specific error code and a short comment saying why.

Don't change runtime behaviour. If a fix would, stop and report it as a concern. If mypy reports more than about 150 errors, report NEEDS_CONTEXT with the count and the top error categories before fixing.

Add more modules to the `ignore_missing_imports` override only when mypy reports "missing library stubs or py.typed marker" for them.

Expected at the end: `Success: no issues found in N source files`.

- [ ] **Step 3: Write the migration-drift test**

`backend/tests/test_migrations.py`:

```python
"""The ORM models and the Alembic migrations must describe the same schema."""

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401  (registers every table)
from app.core.db import Base


def _diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": False}
    )
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        diff = await connection.run_sync(_diff)
    assert diff == [], f"Models and migrations differ; add an Alembic revision: {diff}"
```

The session-scoped `postgres_url` fixture already migrates to head, and the `engine` fixture connects to that database.

Run: `uv run pytest tests/test_migrations.py -q`

- **If it fails** on real differences between the models and the migrations (for example an index or constraint name, or a type), fix the side that is wrong. Usually that means adding the missing `index=True` or `server_default` to a model so it matches what the migrations created. Don't edit old migrations. If the database is right and the model is wrong, fix the model. If the model is right, add migration `0009` with the change.
- The test database holds only this app's tables, so every difference reported is real. `alembic_version` is excluded automatically.

Record every difference you fixed in the report.

Then show the test catches drift. Temporarily add `extra = mapped_column(String(10), nullable=True)` to `AppSetting` and confirm the test fails; then remove it. Paste that output in the report as RED evidence.

- [ ] **Step 4: Run everything**

Run: `uv run mypy && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests/test_migrations.py
git commit -m "chore(backend): mypy clean on app/, test that models match migrations"
```

(Add any new migration file explicitly, if Step 3 created one.)

---

### Task 3: Frontend production image

**Files:**
- Modify: `frontend/next.config.ts`
- Create: `frontend/Dockerfile`, `frontend/.dockerignore`
- Modify: `frontend/README.md` (replace the CLI boilerplate)

**Interfaces:**
- Produces: an image built from `frontend/` with build args `BACKEND_URL` (default `http://api:8000`), `NEXT_PUBLIC_APP_NAME` (default `Knowledge Assistant`) and `NEXT_PUBLIC_PHOENIX_URL` (default `/phoenix`).
  - It listens on port 3000 as a non-root user.
  - It has a `HEALTHCHECK` on `GET /login`.
  - Task 4's compose `frontend` service builds it.

- [ ] **Step 1: Standalone output**

In `frontend/next.config.ts`, add `output: "standalone",` to `nextConfig`. Update the top comment: in production, Caddy routes `/api` to FastAPI, and the rewrite only serves `next start` and `next dev`.

Run `npm run build`. Expected: success, and `.next/standalone/server.js` exists.

- [ ] **Step 2: Dockerfile**

Pin `node:24.x.y-alpine3.xx` to an exact tag that exists. Run `docker pull node:24-alpine`, then read the exact version with `docker run --rm node:24-alpine node --version` and the alpine version from `/etc/alpine-release`, and use the matching full tag (for example `node:24.9.0-alpine3.22`).

`frontend/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
# Exact pinned tag (see above), e.g. node:24.9.0-alpine3.22
ARG NODE_IMAGE=node:24-alpine

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG BACKEND_URL=http://api:8000
ARG NEXT_PUBLIC_APP_NAME="Knowledge Assistant"
ARG NEXT_PUBLIC_PHOENIX_URL=/phoenix
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_PUBLIC_APP_NAME=${NEXT_PUBLIC_APP_NAME} \
    NEXT_PUBLIC_PHOENIX_URL=${NEXT_PUBLIC_PHOENIX_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 nextjs && adduser -S -u 10001 -G nextjs nextjs
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nextjs /app/public ./public
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -qO /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", "server.js"]
```

Replace `node:24-alpine` in the `ARG` line with the exact tag you found.

`frontend/.dockerignore`:

```
node_modules
.next
test-results
playwright-report
e2e
**/*.test.ts
**/*.test.tsx
.env*
Dockerfile
```

- [ ] **Step 3: Build and run it**

```bash
docker build -t rag-frontend:check frontend
docker run --rm -d --name rag-frontend-check -p 127.0.0.1:3999:3000 rag-frontend:check
```

Wait until it's healthy (`docker inspect -f '{{.State.Health.Status}}' rag-frontend-check` returns `healthy`, within about 60 s). Then:
- `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3999/login` must print `200`.
- `docker exec rag-frontend-check id -u` must print `10001`.

Then stop it: `docker stop rag-frontend-check`. Record all outputs in the report.

- [ ] **Step 4: README**

Replace `frontend/README.md` with real notes (40–70 lines) covering:
- **What it is:** the Next.js user app at `/app` and the admin console at `/admin`.
- **Development:**
  - `npm install` (uses `.npmrc` `legacy-peer-deps=true`, needed because `@vitejs/plugin-react` 6 and shadcn's Babel 7 peer ranges conflict);
  - the backend stack started with the dev override `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d`;
  - `npm run dev`, which proxies `/api` to `BACKEND_URL` (default `http://127.0.0.1:8000`).
- **Checks:** `npm run lint`, `typecheck`, `test`, `build`.
- **e2e:** `npm run e2e` with `E2E_BASE_URL`, `E2E_USERNAME` and `E2E_PASSWORD` (a super admin). The global setup (Task 7) seeds a group, a collection and a PDF. The tests need the worker and a real OpenAI key.
- **Production:** built by `deploy/docker-compose.yml` (`frontend` service). Build args: `NEXT_PUBLIC_APP_NAME`, `NEXT_PUBLIC_PHOENIX_URL` and `BACKEND_URL`. They are fixed at build time, so rebuild after changing them. Branding (name, color, logo) is set at runtime in admin Settings.

- [ ] **Step 5: Checks and commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build`

```bash
git add frontend/next.config.ts frontend/Dockerfile frontend/.dockerignore frontend/README.md
git commit -m "feat(frontend): standalone production image and real readme"
```

---
### Task 4: Caddy and the production compose topology

**Files:**
- Create: `deploy/Caddyfile`, `deploy/docker-compose.dev.yml`, `deploy/postgres-init/10-phoenix.sh`
- Modify: `deploy/docker-compose.yml`, `deploy/.env.example`, `.gitignore`

**Interfaces:**
- Consumes: the backend image (Task 1) and the frontend image (Task 3).
- Produces:
  - Compose services `caddy` and `frontend`. Caddy is the only service publishing host ports: `${HTTP_PORT:-80}`, `${HTTPS_PORT:-443}` and `443/udp`.
  - Every backend service reads `env_file: ${RAG_SERVICE_ENV_FILE:-.env}`, so a second stack can use another env file (Task 7).
  - New `.env` keys: `RAG_DOMAIN`, `HTTP_PORT`, `HTTPS_PORT`, `PHOENIX_DB_PASSWORD`, `PHOENIX_BASIC_AUTH_USER`, `PHOENIX_BASIC_AUTH_HASH`, `RAG_SESSION_COOKIE_SECURE` (commented) and `RAG_SERVICE_ENV_FILE` (commented).
  - Task 5's scripts call the services `postgres`, `qdrant`, `api` and the rest by these names.

- [ ] **Step 1: Pin the new images**

Run `docker pull caddy:2.10-alpine` and read the exact version (`docker run --rm caddy:2.10-alpine caddy version`). Use the exact tag, for example `caddy:2.10.2-alpine`. Keep the existing pins for postgres, redis, qdrant, clamav and phoenix.

- [ ] **Step 2: Caddyfile**

`deploy/Caddyfile`:

```caddyfile
# Single entry point. RAG_DOMAIN: a public DNS name (automatic Let's Encrypt), "localhost" or an
# intranet name (Caddy's internal CA), or ":80" for plain HTTP (then set
# RAG_SESSION_COOKIE_SECURE=false in deploy/.env).
{$RAG_DOMAIN:localhost} {
	# A client must never choose the request ID written into audit rows.
	request_header X-Request-ID {http.request.uuid}

	# Compress documents only; never the answer stream (text/event-stream) or binaries.
	encode zstd gzip {
		match {
			header Content-Type text/html*
			header Content-Type text/css*
			header Content-Type text/plain*
			header Content-Type text/csv*
			header Content-Type application/javascript*
			header Content-Type application/json*
			header Content-Type image/svg+xml*
		}
	}

	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "camera=(), microphone=(), geolocation=()"
	}

	# Phoenix (LLM traces) has no login of its own: basic auth, and no app CSP.
	handle /phoenix* {
		basic_auth {
			{$PHOENIX_BASIC_AUTH_USER} {$PHOENIX_BASIC_AUTH_HASH}
		}
		reverse_proxy phoenix:6006
	}

	@app not path /phoenix*
	header @app {
		Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
		X-Frame-Options "DENY"
	}

	@upload path_regexp ^/api/admin/collections/[^/]+/documents$
	handle @upload {
		request_body {
			max_size 500MB
		}
		reverse_proxy api:8000
	}

	handle /api/* {
		request_body {
			max_size 10MB
		}
		# flush_interval -1: stream answers token by token.
		reverse_proxy api:8000 {
			flush_interval -1
		}
	}

	handle {
		reverse_proxy frontend:3000
	}
}
```

Validate it:

```bash
docker run --rm -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -e RAG_DOMAIN=localhost -e PHOENIX_BASIC_AUTH_USER=ops \
  -e PHOENIX_BASIC_AUTH_HASH='$2a$14$abcdefghijklmnopqrstuuJ4rQ0zN2X6wU8fZ0n1yJ2K3lM4nO5pQ6' \
  <caddy image> caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Expected: `Valid configuration`. On Git Bash, prefix the command with `MSYS_NO_PATHCONV=1`.

If `validate` rejects the dummy hash's format, generate a real one with `caddy hash-password --plaintext test`. Use that one for validation only, and never commit it. If Caddy rejects the `encode` `match` syntax, change it to whatever this Caddy version accepts. The requirement is that `text/event-stream` responses are never compressed, and Task 7 checks it on the real stack.

- [ ] **Step 3: Postgres init for Phoenix**

`deploy/postgres-init/10-phoenix.sh`. Commit it with LF line endings and make it executable with `git update-index --chmod=+x`:

```sh
#!/bin/sh
# Runs once, when the Postgres volume is first created: Phoenix gets its own role and database
# (traces hold questions and document text; they don't belong in the app database).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE phoenix LOGIN PASSWORD '${PHOENIX_DB_PASSWORD}';
CREATE DATABASE phoenix OWNER phoenix;
EOSQL
```

Add a `.gitattributes` line `*.sh text eol=lf` at the repo root. Create the file if it doesn't exist.

- [ ] **Step 4: docker-compose.yml**

Rewrite `deploy/docker-compose.yml`. Keep `name: multimodal-rag` and the existing `x-backend-env` block, with these changes:

- **postgres**:
  - Add `PHOENIX_DB_PASSWORD: ${PHOENIX_DB_PASSWORD:?set PHOENIX_DB_PASSWORD in deploy/.env}` to its `environment`.
  - Add the volume `- ./postgres-init:/docker-entrypoint-initdb.d:ro`.
- **qdrant**: add a healthcheck. The image has no curl, so use bash's TCP check:

  ```yaml
      healthcheck:
        test: ["CMD-SHELL", "bash -c ':> /dev/tcp/127.0.0.1/6333' || exit 1"]
        interval: 5s
        timeout: 3s
        retries: 20
  ```

  If the image has no bash, use whatever probe it does support, and report which one.
- **phoenix**:
  - Set `PHOENIX_SQL_DATABASE_URL: postgresql://phoenix:${PHOENIX_DB_PASSWORD}@postgres:5432/phoenix` and `PHOENIX_HOST_ROOT_PATH: /phoenix`.
  - Remove `PHOENIX_SQL_DATABASE_SCHEMA`.
  - Remove the `ports` block (Caddy serves it).
- **api**:
  - Use `env_file: ${RAG_SERVICE_ENV_FILE:-.env}`.
  - Remove the `ports` block.
  - Change `depends_on` qdrant to `condition: service_healthy`.
- **worker** and **worker-eval**:
  - Use the same `env_file`.
  - Add `--max-tasks-per-child=20` to both commands.
  - Set `mem_limit: 6g` on worker and `mem_limit: 3g` on worker-eval.
- **frontend** (new):

  ```yaml
    frontend:
      build:
        context: ../frontend
        args:
          NEXT_PUBLIC_APP_NAME: ${NEXT_PUBLIC_APP_NAME:-Knowledge Assistant}
          NEXT_PUBLIC_PHOENIX_URL: /phoenix
          BACKEND_URL: http://api:8000
      restart: unless-stopped
      depends_on:
        api:
          condition: service_healthy
  ```

- **caddy** (new):

  ```yaml
    caddy:
      image: caddy:<exact tag from Step 1>
      restart: unless-stopped
      environment:
        RAG_DOMAIN: ${RAG_DOMAIN:-localhost}
        PHOENIX_BASIC_AUTH_USER: ${PHOENIX_BASIC_AUTH_USER:?set PHOENIX_BASIC_AUTH_USER in deploy/.env}
        PHOENIX_BASIC_AUTH_HASH: ${PHOENIX_BASIC_AUTH_HASH:?set PHOENIX_BASIC_AUTH_HASH in deploy/.env}
      ports:
        - "${HTTP_PORT:-80}:80"
        - "${HTTPS_PORT:-443}:443"
        - "${HTTPS_PORT:-443}:443/udp"
      volumes:
        - ./Caddyfile:/etc/caddy/Caddyfile:ro
        - caddy-data:/data
        - caddy-config:/config
      depends_on:
        api:
          condition: service_healthy
        frontend:
          condition: service_healthy
  ```

- Add the volumes `caddy-data:` and `caddy-config:`.

`deploy/docker-compose.dev.yml`:

```yaml
# Local development: expose the API and Phoenix to the host so `npm run dev` (frontend/) can use
# them. Usage: docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d
services:
  api:
    ports:
      - "127.0.0.1:8000:8000"
  phoenix:
    environment:
      PHOENIX_HOST_ROOT_PATH: ""
    ports:
      - "127.0.0.1:6006:6006"
```

Validate both files (no secrets are printed):

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env.example config --quiet
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml --env-file deploy/.env.example config --quiet
```

Expected: no output and exit 0. The example file must hold non-empty placeholders for every `:?` variable, so this works.

- [ ] **Step 5: .env.example**

Update `deploy/.env.example`, keeping its existing content. Add:

```
# Public address. A DNS name gets a Let's Encrypt certificate automatically (ports 80/443 must
# be reachable). "localhost" or an intranet name uses Caddy's internal CA (browsers warn until
# it is trusted). ":80" serves plain HTTP: then also set RAG_SESSION_COOKIE_SECURE=false.
RAG_DOMAIN=localhost
# HTTP_PORT=80
# HTTPS_PORT=443
# RAG_SESSION_COOKIE_SECURE=false

# Phoenix (LLM traces) gets its own database. Letters and digits only.
PHOENIX_DB_PASSWORD=changeMePhoenix1

# Phoenix UI at https://<RAG_DOMAIN>/phoenix, behind basic auth. Create the hash with:
#   docker run --rm caddy:<tag> caddy hash-password --plaintext 'your-password'
# Keep the single quotes: the hash contains $ signs.
PHOENIX_BASIC_AUTH_USER=ops
PHOENIX_BASIC_AUTH_HASH='$2a$14$replaceWithYourOwnHashReplaceWithYourOwnHashReplaceWi'

# Advanced: run a second stack with another env file (e.g. a verification install).
# RAG_SERVICE_ENV_FILE=.env
```

Remove the old line about the Phoenix UI on 127.0.0.1:6006.

Check, with the validation run above, that Compose treats the single-quoted value literally. `docker compose ... config` must show the `$2a$14$...` string unchanged in the caddy environment. Run it against `.env.example`, never against the real `.env`.

Add `deploy/.env.verify` and `backups/` to `.gitignore`.

- [ ] **Step 6: Commit**

```bash
git add deploy/Caddyfile deploy/docker-compose.yml deploy/docker-compose.dev.yml deploy/.env.example deploy/postgres-init/10-phoenix.sh .gitattributes .gitignore
git commit -m "feat(deploy): caddy entry point with https, security headers and phoenix auth; frontend service"
```

(Running the full stack happens in Task 7.)

---

### Task 5: Ops scripts and Makefile

**Files:**
- Create: `scripts/lib.sh`, `scripts/backup.sh`, `scripts/restore.sh`, `scripts/create-superadmin.sh`, `scripts/phoenix-db.sh`
- Create: `Makefile`

**Interfaces:**
- Consumes: the compose service names from Task 4, and `python -m app.cli create-superadmin --username --full-name`, which reads `RAG_SUPERADMIN_PASSWORD` if it is set.
- Produces:
  - **Environment:** `RAG_ENV_FILE` (default `deploy/.env`) and `RAG_COMPOSE_PROJECT` (default: the compose file's `name`). Every script honours both, so Task 7 can point them at the `rag-verify` stack.
  - **`make` targets:** `up`, `down`, `ps`, `logs`, `dev`, `create-superadmin`, `backup`, `restore BACKUP=<dir>`, `phoenix-db`.
  - **`scripts/backup.sh [dest]`** writes `postgres.dump`, `phoenix.dump`, `qdrant-<collection>.snapshot`, `files.tar.gz` and `manifest.txt`.
  - **`scripts/restore.sh <dir> [--yes]`** restores those files.

- [ ] **Step 1: Shared helpers**

`scripts/lib.sh`:

```bash
# Shared helpers for the ops scripts. Source it; don't run it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${RAG_ENV_FILE:-$ROOT/deploy/.env}"
export MSYS_NO_PATHCONV=1  # Git Bash on Windows: don't rewrite container paths like /data/files

[ -f "$ENV_FILE" ] || { echo "error: $ENV_FILE not found (copy deploy/.env.example)" >&2; exit 1; }

compose() {
  local project=()
  [ -n "${RAG_COMPOSE_PROJECT:-}" ] && project=(-p "$RAG_COMPOSE_PROJECT")
  docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ENV_FILE" "${project[@]}" "$@"
}

# Value of KEY in the env file, without printing anything else (quotes stripped).
env_value() {
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

qdrant_collection() {
  local name
  name="$(env_value RAG_QDRANT_COLLECTION)"
  printf '%s' "${name:-chunks}"
}
```

- [ ] **Step 2: Backup**

`scripts/backup.sh`:

```bash
#!/usr/bin/env bash
# Backup: Postgres (app + Phoenix), a Qdrant collection snapshot and the files volume, into one
# timestamped folder. deploy/.env (secrets, including RAG_SECRETS_KEY) is NOT copied.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="${1:-$ROOT/backups/$stamp}"
mkdir -p "$dest"
pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
collection="$(qdrant_collection)"

echo "Backing up to $dest"
compose exec -T postgres pg_dump -U "$pg_user" -d "$pg_db" -Fc > "$dest/postgres.dump"
if ! compose exec -T postgres pg_dump -U "$pg_user" -d phoenix -Fc > "$dest/phoenix.dump"; then
  rm -f "$dest/phoenix.dump"
  echo "warning: no phoenix database; traces not backed up (run 'make phoenix-db')" >&2
fi

# Qdrant: create a collection snapshot (from inside the network), copy it out, delete it.
snapshot="$(compose exec -T api python -c '
import json, sys, urllib.request
c = sys.argv[1]
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots?wait=true", method="POST")
print(json.load(urllib.request.urlopen(req, timeout=3600))["result"]["name"])
' "$collection" | tr -d '\r')"
compose cp "qdrant:/qdrant/snapshots/$collection/$snapshot" "$dest/qdrant-$collection.snapshot"
compose exec -T api python -c '
import sys, urllib.request
c, name = sys.argv[1], sys.argv[2]
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots/{name}", method="DELETE")
urllib.request.urlopen(req, timeout=60)
' "$collection" "$snapshot"

compose exec -T api tar -czf - -C /data/files . > "$dest/files.tar.gz"

{
  echo "created_utc=$stamp"
  echo "git_revision=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "alembic_revision=$(compose exec -T postgres psql -U "$pg_user" -d "$pg_db" -tAc 'select version_num from alembic_version' | tr -d '\r')"
  echo "qdrant_collection=$collection"
} > "$dest/manifest.txt"

echo "Done: $dest"
echo "Reminder: back up deploy/.env separately and securely. It holds RAG_SECRETS_KEY;"
echo "without it, API keys saved in admin Settings can't be decrypted after a restore."
```

`docker compose cp` from a service needs the container to be running, as it is in normal operation. If `compose cp` with a service name isn't supported by the installed Compose version, use `docker cp "$(compose ps -q qdrant)":/qdrant/snapshots/... `.

- [ ] **Step 3: Restore**

`scripts/restore.sh`:

```bash
#!/usr/bin/env bash
# Restore a folder made by backup.sh over the current data. Destructive: asks for confirmation.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

dir="${1:?usage: scripts/restore.sh <backup folder> [--yes]}"
[ -f "$dir/postgres.dump" ] || { echo "error: $dir has no postgres.dump" >&2; exit 1; }
name="$(basename "$dir")"
if [ "${2:-}" != "--yes" ]; then
  read -r -p "This replaces ALL current data with backup '$name'. Type the folder name to continue: " answer
  [ "$answer" = "$name" ] || { echo "aborted"; exit 1; }
fi
pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
collection="$(qdrant_collection)"

echo "Stopping the app services"
compose stop caddy frontend worker worker-eval api phoenix
compose up -d --wait postgres qdrant redis

echo "Restoring Postgres"
compose exec -T postgres pg_restore -U "$pg_user" -d "$pg_db" --clean --if-exists --no-owner < "$dir/postgres.dump"
if [ -f "$dir/phoenix.dump" ]; then
  compose exec -T postgres pg_restore -U "$pg_user" -d phoenix --clean --if-exists --no-owner --role=phoenix < "$dir/phoenix.dump" \
    || echo "warning: phoenix traces not restored (run 'make phoenix-db' first)" >&2
fi

echo "Restoring Qdrant collection '$collection'"
snapshot_file="$(ls "$dir"/qdrant-*.snapshot | head -n 1)"
compose exec -T qdrant mkdir -p "/qdrant/snapshots/$collection"
compose cp "$snapshot_file" "qdrant:/qdrant/snapshots/$collection/restore.snapshot"
compose run --rm --no-deps -T api python -c '
import json, sys, urllib.request
c = sys.argv[1]
body = json.dumps({"location": f"file:///qdrant/snapshots/{c}/restore.snapshot", "priority": "snapshot"}).encode()
req = urllib.request.Request(f"http://qdrant:6333/collections/{c}/snapshots/recover?wait=true",
                             data=body, method="PUT", headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=3600))["status"])
' "$collection"
compose exec -T qdrant rm -f "/qdrant/snapshots/$collection/restore.snapshot"

echo "Restoring files"
compose run --rm --no-deps -T api sh -c 'find /data/files -mindepth 1 -delete && tar -xzf - -C /data/files' < "$dir/files.tar.gz"

echo "Starting everything"
compose up -d
echo "Restored '$name'."
```

- `compose up -d --wait` needs Compose 2.17 or later; check `docker compose version`.
- `compose run --rm --no-deps api` starts a one-off api container. Its entrypoint is `CMD`, which the command above overrides, so it doesn't run migrations.
- The `phoenix` database restore runs `pg_restore` as the superuser with `--role=phoenix`, so the restored objects belong to `phoenix`.

- [ ] **Step 4: Superadmin and Phoenix database helpers**

`scripts/create-superadmin.sh`:

```bash
#!/usr/bin/env bash
# Create the first super admin. Prompts for the password unless RAG_SUPERADMIN_PASSWORD is set.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

username="${RAG_SUPERADMIN_USERNAME:-}"
full_name="${RAG_SUPERADMIN_FULL_NAME:-}"
[ -n "$username" ] || read -r -p "Username: " username
[ -n "$full_name" ] || read -r -p "Full name: " full_name
if [ -n "${RAG_SUPERADMIN_PASSWORD:-}" ]; then
  compose exec -T -e RAG_SUPERADMIN_PASSWORD api \
    python -m app.cli create-superadmin --username "$username" --full-name "$full_name"
else
  compose exec api python -m app.cli create-superadmin --username "$username" --full-name "$full_name"
fi
```

`scripts/phoenix-db.sh` (idempotent; for installs created before Plan 8):

```bash
#!/usr/bin/env bash
# Create Phoenix's own role and database on an existing Postgres volume (new installs get them
# from deploy/postgres-init). Safe to run more than once.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

pg_user="$(env_value POSTGRES_USER)"
pg_db="$(env_value POSTGRES_DB)"
phoenix_password="$(env_value PHOENIX_DB_PASSWORD)"
[ -n "$phoenix_password" ] || { echo "error: set PHOENIX_DB_PASSWORD in the env file" >&2; exit 1; }
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$pg_user" -d "$pg_db" \
  -v pw="$phoenix_password" <<'SQL'
SELECT format('CREATE ROLE phoenix LOGIN PASSWORD %L', :'pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'phoenix')
\gexec
SELECT format('ALTER ROLE phoenix PASSWORD %L', :'pw')
\gexec
SELECT 'CREATE DATABASE phoenix OWNER phoenix'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'phoenix')
\gexec
SQL
echo "Phoenix database ready. Restart Phoenix: docker compose -f deploy/docker-compose.yml up -d phoenix"
```

- [ ] **Step 5: Makefile**

`Makefile` (recipes must be indented with tabs):

```make
# Operator commands (spec §8). On Windows, run the scripts with Git Bash: bash scripts/<name>.sh
SHELL := bash
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: up down ps logs dev create-superadmin backup restore phoenix-db

up:                  ## Build and start everything
	$(COMPOSE) up -d --build

down:                ## Stop everything (data volumes are kept)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

dev:                 ## Start the stack with the API (8000) and Phoenix (6006) on localhost
	$(COMPOSE) -f deploy/docker-compose.dev.yml up -d --build

create-superadmin:   ## Create the first super admin (prompts)
	bash scripts/create-superadmin.sh

backup:              ## Back up Postgres, Qdrant and files to backups/<UTC timestamp>/
	bash scripts/backup.sh

restore:             ## Restore: make restore BACKUP=backups/<folder>
	@test -n "$(BACKUP)" || { echo "usage: make restore BACKUP=backups/<folder>"; exit 1; }
	bash scripts/restore.sh "$(BACKUP)"

phoenix-db:          ## Create Phoenix's database on an install made before Plan 8
	bash scripts/phoenix-db.sh
```

- [ ] **Step 6: Static checks**

- Run `docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:stable scripts/*.sh deploy/postgres-init/*.sh`, with `MSYS_NO_PATHCONV=1` on Git Bash. Fix every warning, or add a targeted `# shellcheck disable=SCxxxx` with a reason for false positives, such as `source` of `lib.sh` (SC1091).
- Run `bash -n` on each script.
- If `make` is installed, run `make -n backup` and check the output. If it isn't, say so.

The real backup and restore round trip runs in Task 7.

- [ ] **Step 7: Commit**

Mark the scripts executable with `git update-index --chmod=+x scripts/*.sh` after adding them.

```bash
git add Makefile scripts
git update-index --chmod=+x scripts/backup.sh scripts/restore.sh scripts/create-superadmin.sh scripts/phoenix-db.sh
git commit -m "feat(ops): make targets and scripts for backup, restore, superadmin and phoenix db"
```

---

### Task 6: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest -q` in `backend/`; `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` in `frontend/`; `backend/Dockerfile` and `frontend/Dockerfile`.
- Produces: three jobs, `backend`, `frontend` and `images`, on every push and pull request.

- [ ] **Step 1: Workflow**

Use the current major versions of each action. Check them on GitHub (for example with `gh api repos/actions/checkout/releases/latest --jq .tag_name`, or the releases page) and use the major tag, for example `actions/checkout@v5`. Pin uv to the version the Dockerfile uses (`0.11.16`) and Node to the major the frontend image uses (24).

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  backend:
    runs-on: ubuntu-24.04
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@<major>
      - uses: astral-sh/setup-uv@<major>
        with:
          version: "0.11.16"
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy
      - run: uv run pytest -q  # testcontainers uses the runner's Docker

  frontend:
    runs-on: ubuntu-24.04
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@<major>
      - uses: actions/setup-node@<major>
        with:
          node-version: "24"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      - run: npm run build

  images:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@<major>
      - uses: docker/setup-buildx-action@<major>
      - uses: docker/build-push-action@<major>
        with:
          context: backend
          push: false
          cache-from: type=gha,scope=backend
          cache-to: type=gha,mode=max,scope=backend
      - uses: docker/build-push-action@<major>
        with:
          context: frontend
          push: false
          cache-from: type=gha,scope=frontend
          cache-to: type=gha,mode=max,scope=frontend
```

- [ ] **Step 2: Lint the workflow**

Run `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color`, with `MSYS_NO_PATHCONV=1` on Git Bash. Expected: no findings. Fix any it reports.

The workflow can only really run once the branch is pushed. Record in the report that it was linted but not executed.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: ruff, mypy, pytest, frontend checks and image builds on every push"
```

---

### Task 7: Fresh-install verification, e2e seeding, docs and follow-ups

**Files:**
- Create: `frontend/e2e/global-setup.ts`, `frontend/e2e/fixtures/leave-policy.pdf`
- Modify: `frontend/playwright.config.ts`
- Create: `README.md` (repository root)
- Create: `docs/superpowers/plans/2026-10-08-plan-8-followups.md`
- Local only, never committed: `deploy/.env.verify`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Playwright `globalSetup` that idempotently seeds what both e2e specs need: a group `e2e-staff` containing the e2e user, and a collection `E2E Handbook` granted to that group, holding `leave-policy.pdf`, waited until ready.
  - The root README.
  - The follow-ups doc.

- [ ] **Step 1: e2e seed**

`frontend/e2e/fixtures/leave-policy.pdf`: a small text PDF (not a scanned image) whose page 1 says exactly: "Annual leave policy. Employees get twenty (20) days of annual leave per year." Generate it once with a throwaway script, e.g. `uv run --with reportlab python -c ...` from any folder. Commit only the PDF, not the script. Keep it under 10 KB.

`frontend/e2e/global-setup.ts`:

```ts
import path from "node:path"
import { readFile } from "node:fs/promises"

import { request, type FullConfig } from "@playwright/test"

const CSRF = { "X-CSRF-Protection": "1" }
const GROUP = "e2e-staff"
const COLLECTION = "E2E Handbook"
const PDF = "leave-policy.pdf"

/** Seeds what the specs need, idempotently: the e2e user in a group that can see a collection
 * holding a leave-policy PDF that is fully ingested. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!
  const api = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: config.projects[0].use.ignoreHTTPSErrors,
  })
  const login = await api.post("/api/auth/session", {
    data: {
      username: process.env.E2E_USERNAME ?? "root",
      password: process.env.E2E_PASSWORD ?? "root-password-123",
    },
  })
  if (!login.ok()) throw new Error(`e2e login failed: ${login.status()}`)
  const me = await (await api.get("/api/auth/me")).json()

  const groups: { id: string; name: string }[] = await (await api.get("/api/admin/groups")).json()
  let group = groups.find((g) => g.name === GROUP)
  if (!group) {
    group = await (
      await api.post("/api/admin/groups", { headers: CSRF, data: { name: GROUP, description: "" } })
    ).json()
  }
  const myGroups: string[] = me.groups.map((g: { id: string }) => g.id)
  if (!myGroups.includes(group!.id)) {
    await api.patch(`/api/admin/users/${me.id}`, {
      headers: CSRF,
      data: { group_ids: [...myGroups, group!.id] },
    })
  }

  const collections: { id: string; name: string }[] = await (
    await api.get("/api/admin/collections")
  ).json()
  let collection = collections.find((c) => c.name === COLLECTION)
  if (!collection) {
    collection = await (
      await api.post("/api/admin/collections", {
        headers: CSRF,
        data: { name: COLLECTION, description: "", group_ids: [group!.id], sensitive: false },
      })
    ).json()
  }

  const buffer = await readFile(path.join(import.meta.dirname, "fixtures", PDF))
  await api.post(`/api/admin/collections/${collection!.id}/documents`, {
    headers: CSRF,
    multipart: { files: { name: PDF, mimeType: "application/pdf", buffer } },
  }) // a duplicate on reruns is fine

  const deadline = Date.now() + 240_000
  for (;;) {
    const docs: { filename: string; versions: { status: string }[] }[] = await (
      await api.get(`/api/admin/collections/${collection!.id}/documents`)
    ).json()
    const status = docs.find((d) => d.filename === PDF)?.versions.at(-1)?.status
    if (status === "ready") break
    if (status === "failed" || status === "rejected" || Date.now() > deadline)
      throw new Error(`seed document not ready: ${status ?? "missing"}`)
    await new Promise((r) => setTimeout(r, 3000))
  }
  await api.dispose()
}
```

Version order: check the order of `versions` in the API's response. If the newest version isn't last, choose the version with the highest `version_no`.

In `frontend/playwright.config.ts`, add `globalSetup: "./e2e/global-setup.ts"`. Under `use`, add `ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === "1"` (Caddy's internal CA on `localhost`).

Run `npm run lint && npm run typecheck`.

- [ ] **Step 2: Fresh install on an isolated stack**

All commands use the `rag-verify` project and its own env file, so the dev stack (`multimodal-rag`) and its volumes are never touched. Never print `deploy/.env` or `deploy/.env.verify`.

1. **Create `deploy/.env.verify`** from `deploy/.env.example`:
   - Use fresh random secrets: `RAG_JWT_SECRET`, `RAG_SECRETS_KEY`, `POSTGRES_PASSWORD` and `PHOENIX_DB_PASSWORD` (letters and digits).
   - Set the Phoenix basic-auth user `ops`, with a hash made by `caddy hash-password` from a password you generate (single-quoted).
   - Set `RAG_DOMAIN=localhost`, `HTTP_PORT=8080`, `HTTPS_PORT=8443` and `RAG_SERVICE_ENV_FILE=.env.verify`.
   - Copy the `RAG_OPENAI_API_KEY=` line from `deploy/.env` without displaying it: `grep '^RAG_OPENAI_API_KEY=' deploy/.env >> deploy/.env.verify`.
   - Keep the generated passwords in shell variables only, never in output.
2. **Start it:**

   ```bash
   export RAG_ENV_FILE=deploy/.env.verify RAG_COMPOSE_PROJECT=rag-verify
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env.verify -p rag-verify up -d --build --wait
   ```

   Every service must reach `healthy` or `running`. Clamav can take up to 5 minutes. Record `docker compose ... ps`.
3. **Create the super admin:** `RAG_SUPERADMIN_USERNAME=verifyroot RAG_SUPERADMIN_FULL_NAME="Verify Root" RAG_SUPERADMIN_PASSWORD=<generated> bash scripts/create-superadmin.sh`. This is spec §1.2 criterion 6.
4. **HTTP checks**, all through `https://localhost:8443` with `curl -k`. Record the commands and results:
   - `GET /login` returns 200 and carries `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options` and `Strict-Transport-Security`, with no `Server` header.
   - `GET /api/health` returns 200. With `-H 'X-Request-ID: forged'`, the echoed `x-request-id` is **not** `forged`.
   - `GET /phoenix/` returns 401 without auth, and 200 with `-u ops:<password>`. The page's own assets also load: fetch one script URL found in the HTML.
     - **If the assets 404**, Phoenix expects the prefix stripped. Switch the Caddy block to `handle_path /phoenix*`, keep `PHOENIX_HOST_ROOT_PATH=/phoenix`, and re-check.
     - Record which variant works.
   - A POST of 11 MB to `/api/auth/session` returns 413.
   - `http://localhost:8080/` redirects to HTTPS. A redirect to port 443 rather than 8443 is expected here and is fine; note it.
5. **Run the e2e:**

   ```bash
   cd frontend && E2E_BASE_URL=https://localhost:8443 E2E_IGNORE_HTTPS_ERRORS=1 \
     E2E_USERNAME=verifyroot E2E_PASSWORD=<generated> npm run e2e
   ```

   Expected: 2 passed. The global setup seeds the data first.
6. **Check that streaming works through Caddy:**
   - Sign in with curl, storing the cookie jar: `POST /api/auth/session`.
   - `POST /api/chat` with `-N`, header `X-CSRF-Protection: 1`, and the question "How many days of annual leave do employees get?". Prefix every received line with a timestamp, for example `while IFS= read -r l; do printf '%s %s\n' "$(date +%s.%N)" "$l"; done`.
   - Expected: several `event: token` lines with increasing timestamps, spread over at least about 0.3 s before `event: done`. Also, the response is not gzip/zstd-encoded: check its `content-encoding` header with `-D -`.
7. **Trace link:** take the `trace_id` from the `done` event. `GET /phoenix/redirects/traces/<trace_id>` with basic auth must not return 404. Note the actual status. If Phoenix lacks this route, record it; the console then shows the ID instead, which is the Plan 7 fallback.
8. **Backup, total loss, restore:**

   ```bash
   bash scripts/backup.sh backups/verify
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env.verify -p rag-verify down -v
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env.verify -p rag-verify up -d --wait
   bash scripts/restore.sh backups/verify --yes
   ```

   Wait until the stack is healthy, then re-run step 6's chat (the answer cites `leave-policy.pdf`). Fetch the page image `GET /api/documents/<doc id>/pages/1`: 200, `image/png`. Then run the e2e again: 2 passed. Record everything.

   `down -v` here applies only to the `rag-verify` project, as the global constraints allow. Double-check the `-p rag-verify` flag before running it.
9. **Tear down:** `docker compose ... -p rag-verify down -v`, then delete `deploy/.env.verify` and `backups/verify`. Confirm that `docker volume ls` still lists the `multimodal-rag_*` volumes.

If a check fails, fix the cause in the right file (Caddyfile, compose, scripts, global setup), re-run the affected checks, and commit the fix with the rest of this task. List every such fix in the report and in the follow-ups doc.

- [ ] **Step 3: Root README**

Write `README.md` at the repository root, about 120–200 lines:
- **What it is:** one paragraph from spec §1.
- **Requirements:** Docker + Compose 2.17 or later, 4 vCPU and 16 GB RAM for a medium install, 8 vCPU, 32 GB RAM and 500 GB SSD for a large one (spec §8.3), and an OpenAI API key.
- **Install:**
  1. `cp deploy/.env.example deploy/.env`.
  2. Fill it in: how to generate each secret (the commands are in the file), and the three `RAG_DOMAIN` modes, including the `:80` plus `RAG_SESSION_COOKIE_SECURE=false` caveat.
  3. `docker compose -f deploy/docker-compose.yml up -d` (or `make up`).
  4. `make create-superadmin` (Windows: `bash scripts/create-superadmin.sh`).
  5. Open `https://<domain>`.
- **Upgrade:** `git pull`, `docker compose ... up -d --build`; migrations run automatically. Installs made before Plan 8 must run `make phoenix-db` once, then `up -d`.
- **Backup and restore:** `make backup`, `make restore BACKUP=...`, what is inside a backup, the cron example `0 2 * * * cd /opt/rag && make backup`, and **back up `deploy/.env` separately** (`RAG_SECRETS_KEY`).
- **Operations:** where logs go (JSON, with request IDs), `/phoenix` (basic auth), health (`docker compose ps`), and the ingestion limits (100 MB per file, 500 MB per upload request).
- **Development:** `make dev` plus `frontend/` `npm run dev` (link to `frontend/README.md`), and the backend tests (`cd backend && uv run pytest`).
- **CI:** what it runs, and that e2e is manual.
- **Security notes:** HTTPS, the CSP, admin-only Phoenix, and the password re-entry for destructive actions.

- [ ] **Step 4: Follow-ups doc**

Write `docs/superpowers/plans/2026-10-08-plan-8-followups.md`, shaped like the Plan 7 follow-ups:
- **Rulings made during execution:** copy every `Ruling:` line from the SDD ledger.
- **End-to-end verification:** every Step 2 check, with its real result. Say plainly what passed, what failed and what wasn't checked.
- **Deferred minor findings:** from the ledger.
- **Remaining work after v1:** ideas only; for example a pinned-digest image registry, scheduled backups, and the e2e in CI with a secret.

- [ ] **Step 5: Final verification and commit**

Run:
- `cd backend && uv run mypy && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`

Expected: all green.

```bash
git add frontend/e2e/global-setup.ts frontend/e2e/fixtures/leave-policy.pdf frontend/playwright.config.ts README.md docs/superpowers/plans/2026-10-08-plan-8-followups.md
git commit -m "test(e2e): seeding global setup; docs: install/operations readme and plan 8 follow-ups"
```

Add any files fixed during Step 2 to the same commit, by explicit path.
