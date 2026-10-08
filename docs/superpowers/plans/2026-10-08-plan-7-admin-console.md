# Plan 7 — Admin Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The admin console (`/admin`) from spec §6.5. Admins manage documents, collections, users and groups, run evaluations, work the review queue, read and export the audit log, and see a dashboard. Super admins also edit models, RAG config and guardrails, and edit Settings (encrypted OpenAI key, branding with name, color and logo).

**Architecture:**
- **Backend (Tasks 1–3).** Most admin APIs already exist (Plans 1–5). This plan adds:
  - an `app_settings` table holding branding and a Fernet-encrypted OpenAI key;
  - a `KeyRing` that every provider call reads (the database key first, then `RAG_OPENAI_API_KEY`);
  - public branding endpoints;
  - a dashboard endpoint computed from Postgres;
  - audit-log filters with keyset paging and CSV export.
- **Frontend (Tasks 4–11).** It extends the Plan 6 app:
  - `/admin` pages use the shadcn sidebar, data table (TanStack Table), form, tabs and chart patterns (spec §6.8).
  - They reuse `apiJson`, the global 401 handling, react-hook-form + zod and `navigateTo`.
  - Branding is fetched from `/api/branding` and applied on the client: name, logo and the `--primary` color.
- **Testing (Task 12):** one Playwright test covers the admin upload flow on the real stack (spec §9).

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy 2 async, Alembic, `cryptography` (Fernet), Pillow (logo check).
- Frontend: Next.js 16, React 19, shadcn 4.21.4 (`table`, `tabs`, `native-select`, `switch`, `checkbox`, `chart`), `@tanstack/react-table` 8, `recharts` (pulled in by shadcn `chart`), TanStack Query 5, react-hook-form + zod 4.
- Testing: Vitest + Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md`:
- §6.5 admin console pages; §6.2 roles; §6.6 privacy; §6.8 frontend foundation; §6.9 audit log;
- §5.3 destructive actions need password re-entry; §7.1 evaluation and the activation warning; §7.2 the dashboard and trace links.

## Decisions this plan relies on (made with the user, 2026-10-08)

- **OpenAI key:**
  - The OpenAI key is stored **encrypted in the database** and edited in Settings by a super_admin.
  - It is Fernet-encrypted with `RAG_SECRETS_KEY` from `.env`. The backend uses it first and falls back to `RAG_OPENAI_API_KEY`.
  - The key is never shown back; only its last 4 characters are.
- **Branding = app name + primary color + logo upload.**

## Rulings made while planning

- **All of Settings is super_admin only.** Spec §6.2 lists only super_admin for keys, and admin rights don't include Settings. Saving or clearing the API key needs password re-entry. Branding doesn't, because it isn't destructive.
  - Cost if wrong: admins ask a super_admin to change branding.
- **Models & RAG config and Guardrails are super_admin pages** (spec §6.2).
  - Guardrail settings live inside RagConfig (Plan 4), so saving on the Guardrails page creates a **new RagConfig version** that still needs activation.
  - It isn't activated automatically, so a guardrail change follows the same versioned flow with eval scores and rollback.
  - Cost: two clicks instead of one.
- **Logo:**
  - PNG, JPEG or WebP, at most 512 KB, and checked with Pillow. **No SVG**, because an SVG served from our origin can run script.
  - It is stored in the FileStore at `branding/logo`.
  - It is served publicly with `X-Content-Type-Options: nosniff` and a version query string, so caches pick up a new logo at once.
- **Key rotation reaches every process without a restart.**
  - `KeyRing.refresh()` re-reads the database at most every 30 s. The chat route calls it before each answer, the API refreshes immediately after a save, and each ingestion or eval task loads the key when it starts.
  - Cached LangChain clients are keyed by the key itself, so a new key gets new clients.
  - A saved key that can't be decrypted (wrong `RAG_SECRETS_KEY`) logs a warning and falls back to the environment key. Settings shows it as `unreadable`.
- **The dashboard is computed live from Postgres** over 7, 30 or 90 days, in UTC days. It covers:
  - questions (assistant messages) and active users (distinct askers);
  - tokens and cost (`usage_records`);
  - the 👍 rate (👍 out of rated answers);
  - the "I don't know" rate (`not_found` out of questions) and the low-confidence rate (out of `answered`);
  - guardrail blocks (`guardrail_events.action = 'blocked'`);
  - ingestion counts (the existing `status_counts`) and health (database, Qdrant, Redis, each with a 2 s timeout).
- **Audit log:**
  - **Filters:** actor username (exact, case-insensitive), action prefix (e.g. `user.`), target type and id, and a date range.
  - **Paging:** keyset paging with `before_id`.
  - **CSV export:** at most 100 000 rows, streamed from its own DB session. Cells starting with `= + - @ \t \r` get a leading `'` to block spreadsheet formula injection. The export itself is audited (`audit.exported`).
- **Trace links:**
  - `ReviewAnswer` gains `trace_id`.
  - The console links to `${NEXT_PUBLIC_PHOENIX_URL}/redirects/traces/<trace_id>` when that build-time variable is set, and otherwise shows the id.
  - Cost if wrong: a broken link with the id still visible.
- **One shared `MeGate`** replaces the user-loading gate in the `/app` layout and also guards `/admin`. Non-admins are sent to `/app` and forced password changes to `/change-password`.
- **Notifications:** a page lists them, and the sidebar shows an unread count (refetched every 60 s). There are no push notifications.
- **Form selects use the shadcn `native-select`**, not the Radix `select`. It is accessible, works with `register()`, and is testable in jsdom.
  - Forms with validation use react-hook-form + zod.
  - Single-purpose inputs without rules (password confirmation, the add-to-test-set form, the API key field) use plain state. The API key is kept out of form state on purpose.
- **Cost caps and the fallback model stay on the Guardrails and Models pages, not Settings.** Spec §6.5 lists them under Settings, but they are versioned inside RagConfig (Plans 3–4). The Settings page says where they are.
  - Cost if wrong: one more click for admins.

## Scope limits (deferred, by design)

- No group rename or delete, and no collection delete. Spec §6.5 asks only for create, assign and mark sensitive. Group membership is edited on the user.
- Strike history per user isn't shown. The Users page shows the chat lock and lets an admin unlock it, which also resets strikes.
- Branding color is a single primary color used in both light and dark mode.
- Frontend Docker, Caddy, CSP and CI → **Plan 8**.

## Global Constraints

- **Roles (spec §6.2):**
  - `admin` gets Dashboard, Documents, Collections & access, Users & groups, Evaluation, Review queue, Audit log and Notifications.
  - `super_admin` also gets Models & RAG config, Guardrails and Settings, and manages admins.
  - Every API route checks the role on the server. The UI hides links the user can't use.
- **Destructive actions need a confirmation dialog and password re-entry (spec §5.3):**
  - deleting a document;
  - changing a collection's groups;
  - activating or rolling back a RagConfig;
  - saving or clearing the OpenAI key.
- Admins see user conversations only through the review queue. Every view is audited, which the backend already does (spec §6.6).
- **Components come from the official shadcn registry:** `npx shadcn@4.21.4 add <name>` puts them into `frontend/components/ui` (spec §6.8). Data tables use `@tanstack/react-table`, charts use the shadcn `chart` (Recharts), and forms use react-hook-form + zod.
- Never use `dangerouslySetInnerHTML`. User or document text renders as plain text, or through the existing sanitized `Markdown` component.
- Next.js 16: read `frontend/AGENTS.md`. Client pages read route params with `useParams()`.
- Every unsafe request goes through `apiFetch`, so the CSRF header is always added.
- **Backend:** ruff (line length 100) and the full pytest suite stay green. New tables are added with Alembic migration `0008`.
- **Frontend:** `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` all pass.
- Never print or commit `deploy/.env`, `RAG_OPENAI_API_KEY` or `RAG_SECRETS_KEY`.

## Review Focus

1. **The saved API key leaking.**
   - No API response, audit entry or log line may contain more than the key's last 4 characters, and the database stores only ciphertext.
   - Tests in Task 1 (`test_key_is_stored_encrypted_and_never_returned`) and Task 2 (`test_openai_key_endpoints_never_echo_the_key`).
2. **A logo that isn't really an image.** An HTML or SVG file renamed to `.png`, or an oversized file, must be rejected, and the served logo must carry `nosniff`. Test in Task 2 (`test_logo_rejects_non_images_and_svg`).
3. **Audit CSV formula injection.** A username or detail beginning with `=` must be exported as inert text. Test in Task 3 (`test_audit_export_is_csv_safe_and_audited`).
4. **A destructive action with a wrong password** must keep the dialog open, show "Re-enter your password to confirm" and change nothing. Test in Task 4 (`keeps the dialog open on a wrong password`) and Task 6 (`asks for a password only when groups change`).
5. **A non-admin opening `/admin`, or an admin opening a super-admin page,** is redirected to `/app` or shown "Only super admins can open this page." Their data never loads. Tests in Task 4 (`sends non-admins to /app` and `hides super-admin pages from admins`).

---

## File structure (new or changed)

```
backend/
  pyproject.toml, uv.lock                       # + cryptography                          (T1)
  app/core/config.py                            # + secrets_key (Fernet)                  (T1)
  app/settings_store/__init__.py, models.py, service.py   # app_settings, branding, key   (T1)
  app/llm/keys.py                               # KeyRing                                  (T1)
  app/llm/gateway.py                            # optional api_key override               (T1)
  app/chat/wiring.py, app/main.py, app/api/chat.py,
  app/ingestion/tasks.py, app/evaluation/tasks.py, app/evaluation/scoring.py  # use KeyRing (T1)
  app/models.py                                 # + AppSetting                             (T1)
  migrations/versions/0008_app_settings.py                                                 (T1)
  app/api/settings.py, app/api/router.py        # branding (public) + admin settings       (T2)
  app/dashboard/__init__.py, service.py, app/api/admin_dashboard.py                        (T3)
  app/audit/service.py, app/audit/schemas.py, app/api/admin.py   # filters, export        (T3)
  app/evaluation/schemas.py                     # ReviewAnswer.trace_id                    (T3)
  tests/test_app_settings.py, tests/test_settings_api.py, tests/test_dashboard_audit.py,
  tests/test_auth.py (PUBLIC_ROUTES)
frontend/
  components/ui/{table,tabs,native-select,switch,checkbox,chart}.tsx    # shadcn add       (T4)
  lib/types.ts (+ admin types), lib/admin-api.ts, lib/roles.ts, lib/branding.ts, lib/format.ts (T4)
  components/me-gate.tsx, components/branding.tsx, components/providers.tsx               (T4)
  components/admin/{admin-sidebar,data-table,password-dialog,page-header,super-admin-only,
                    group-checklist}.tsx                                                   (T4)
  app/admin/layout.tsx, app/app/layout.tsx (MeGate), proxy.ts, components/user-menu.tsx,
  components/app-sidebar.tsx, components/auth/auth-layout.tsx                              (T4)
  app/admin/page.tsx, components/admin/questions-chart.tsx, app/admin/notifications/page.tsx (T5)
  app/admin/collections/page.tsx, components/admin/collection-dialog.tsx,
  app/admin/users/page.tsx, components/admin/user-dialogs.tsx                              (T6)
  app/admin/documents/page.tsx, components/admin/document-sheet.tsx                        (T7)
  app/admin/review/page.tsx, components/admin/review-sheet.tsx, app/admin/audit/page.tsx   (T8)
  app/admin/evaluation/page.tsx, app/admin/evaluation/sets/[id]/page.tsx,
  app/admin/evaluation/runs/[id]/page.tsx, app/admin/evaluation/compare/page.tsx,
  components/admin/{case-dialog,compare-view,run-summary}.tsx                              (T9)
  app/admin/models/page.tsx, app/admin/guardrails/page.tsx,
  components/admin/activate-dialog.tsx, lib/config-version.ts                              (T10)
  app/admin/settings/page.tsx                                                              (T11)
  e2e/admin.spec.ts                                                                        (T12)
docs/superpowers/plans/2026-10-08-plan-7-followups.md                                     (T12)
```

---

### Task 1: App settings store, encrypted OpenAI key, KeyRing

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (via `uv add`)
- Modify: `backend/app/core/config.py`
- Create: `backend/app/settings_store/__init__.py` (empty), `backend/app/settings_store/models.py`, `backend/app/settings_store/service.py`
- Create: `backend/app/llm/keys.py`
- Modify: `backend/app/llm/gateway.py`, `backend/app/chat/wiring.py`, `backend/app/main.py`, `backend/app/api/chat.py`, `backend/app/ingestion/tasks.py`, `backend/app/evaluation/tasks.py`, `backend/app/evaluation/scoring.py`, `backend/app/models.py`
- Create: `backend/migrations/versions/0008_app_settings.py`
- Test: `backend/tests/test_app_settings.py`

**Interfaces:**
- Consumes:
  - `app.audit.service.record(session, *, action, actor, target_type, target_id, detail)`;
  - `FileStore.save/read/delete_prefix`;
  - `Settings.openai_api_key`.
- Produces (Task 2 uses all of these):
  - `app.settings_store.service`:
    - `Branding(app_name: str, primary_color: str | None)` and `BrandingOut(Branding)` with `logo_url: str | None`;
    - `KeyStatus(source: Literal["database","environment","none","unreadable"], last4: str | None, updated_at: datetime | None, secrets_key_configured: bool)`;
    - `SettingsError(code, message)`, with `SecretsKeyMissing` (code `secrets_key_missing`) and `InvalidLogo` (code `invalid_logo`).
  - `async get_branding(session) -> BrandingOut`
  - `async update_branding(session, actor, branding: Branding) -> BrandingOut`
  - `async set_logo(session, store, actor, data: bytes) -> BrandingOut`
  - `async clear_logo(session, store, actor) -> BrandingOut`
  - `async read_logo(session, store) -> tuple[bytes, str] | None` (bytes, content type)
  - `async openai_key_status(session, settings) -> KeyStatus`
  - `async set_openai_key(session, settings, actor, api_key: str) -> KeyStatus`
  - `async clear_openai_key(session, settings, actor) -> KeyStatus`
  - `async resolve_openai_key(session, settings) -> SecretStr | None`
  - `app.llm.keys.KeyRing(settings, sessionmaker, ttl=30.0, clock=time.monotonic)` with `async refresh(force=False)` and `openai() -> SecretStr | None`.
  - `app.state.keys` is a `KeyRing`.
  - Gateway functions accept `api_key: SecretStr | None = None` and fall back to `settings.openai_api_key`.

- [ ] **Step 1: Add the dependency**

Run (in `backend/`): `uv add cryptography`
Expected: `pyproject.toml` lists `cryptography>=…` and `uv.lock` updates. Check that `openai` stays at 3.26.x: `uv pip show openai`.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_app_settings.py`:

```python
import io
import logging

import pytest
from cryptography.fernet import Fernet
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.audit.models import AuditLog
from app.core.config import Settings
from app.core.db import create_sessionmaker
from app.core.storage import LocalFileStore
from app.llm.keys import KeyRing
from app.settings_store import service
from app.settings_store.models import AppSetting
from app.users.models import Role
from tests.factories import make_user

SECRET = "sk-test-0123456789abcdefWXYZ"


def _settings(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(update=overrides)


def _png(size: tuple[int, int] = (4, 4)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return buffer.getvalue()


def test_secrets_key_must_be_a_fernet_key() -> None:
    with pytest.raises(ValueError, match="RAG_SECRETS_KEY"):
        Settings(_env_file=None, jwt_secret="x" * 40, secrets_key="not-a-key")
    Settings(_env_file=None, jwt_secret="x" * 40, secrets_key=Fernet.generate_key().decode())


async def test_key_is_stored_encrypted_and_never_returned(
    session: AsyncSession, settings: Settings
) -> None:
    admin = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    cfg = _settings(settings, secrets_key=SecretStr(Fernet.generate_key().decode()))

    status = await service.set_openai_key(session, cfg, admin, SECRET)
    await session.commit()

    assert status.source == "database"
    assert status.last4 == "WXYZ"
    assert SECRET not in status.model_dump_json()
    row = await session.get(AppSetting, "openai_api_key")
    assert row is not None and SECRET not in str(row.value)
    entries = (await session.scalars(select(AuditLog))).all()
    assert [e.action for e in entries] == ["settings.openai_key_set"]
    assert SECRET not in str(entries[0].detail)
    resolved = await service.resolve_openai_key(session, cfg)
    assert resolved is not None and resolved.get_secret_value() == SECRET


async def test_saving_a_key_needs_the_secrets_key(
    session: AsyncSession, settings: Settings
) -> None:
    admin = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    with pytest.raises(service.SecretsKeyMissing):
        await service.set_openai_key(session, _settings(settings, secrets_key=None), admin, SECRET)


async def test_environment_fallback_and_unreadable_key(
    session: AsyncSession, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    admin = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    env_only = _settings(settings, openai_api_key=SecretStr("sk-env-key-0000000000001234"))
    status = await service.openai_key_status(session, env_only)
    assert (status.source, status.last4) == ("environment", "1234")
    assert (await service.openai_key_status(session, settings)).source == "none"

    saved_with = _settings(env_only, secrets_key=SecretStr(Fernet.generate_key().decode()))
    await service.set_openai_key(session, saved_with, admin, SECRET)
    rotated = _settings(env_only, secrets_key=SecretStr(Fernet.generate_key().decode()))
    assert (await service.openai_key_status(session, rotated)).source == "unreadable"
    with caplog.at_level(logging.WARNING):
        resolved = await service.resolve_openai_key(session, rotated)
    assert resolved is not None and resolved.get_secret_value().endswith("1234")
    assert "can't be decrypted" in caplog.text

    cleared = await service.clear_openai_key(session, saved_with, admin)
    assert cleared.source == "environment"


async def test_branding_defaults_update_and_logo(
    session: AsyncSession, settings: Settings
) -> None:
    admin = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    store = LocalFileStore(settings.files_dir)
    default = await service.get_branding(session)
    assert (default.app_name, default.primary_color, default.logo_url) == (
        "Knowledge Assistant",
        None,
        None,
    )

    updated = await service.update_branding(
        session, admin, service.Branding(app_name="Acme Docs", primary_color="#1D4ED8")
    )
    assert (updated.app_name, updated.primary_color) == ("Acme Docs", "#1D4ED8")

    with_logo = await service.set_logo(session, store, admin, _png())
    assert with_logo.logo_url is not None
    assert with_logo.logo_url.startswith("/api/branding/logo?v=")
    assert with_logo.app_name == "Acme Docs"
    logo = await service.read_logo(session, store)
    assert logo is not None and logo[1] == "image/png"

    for bad in (b"<svg onload=alert(1)></svg>", b"<html>hi</html>", b"\x89PNG broken"):
        with pytest.raises(service.InvalidLogo):
            await service.set_logo(session, store, admin, bad)
    with pytest.raises(service.InvalidLogo, match="512 KB"):
        await service.set_logo(session, store, admin, b"x" * (512 * 1024 + 1))

    cleared = await service.clear_logo(session, store, admin)
    assert cleared.logo_url is None
    assert await service.read_logo(session, store) is None
    actions = [e.action for e in (await session.scalars(select(AuditLog))).all()]
    assert actions == [
        "settings.branding_updated",
        "settings.logo_updated",
        "settings.logo_removed",
    ]


async def test_keyring_reloads_after_ttl(engine: AsyncEngine, settings: Settings) -> None:
    sessionmaker = create_sessionmaker(engine)
    cfg = _settings(
        settings,
        openai_api_key=SecretStr("sk-env-key-0000000000001234"),
        secrets_key=SecretStr(Fernet.generate_key().decode()),
    )
    now = [100.0]
    ring = KeyRing(cfg, sessionmaker, ttl=30.0, clock=lambda: now[0])
    assert ring.openai() is not None  # env key before the first refresh
    await ring.refresh()
    assert ring.openai().get_secret_value().endswith("1234")  # type: ignore[union-attr]

    async with sessionmaker() as session:
        admin = await make_user(session, username="root", role=Role.SUPER_ADMIN)
        await service.set_openai_key(session, cfg, admin, SECRET)
        await session.commit()

    now[0] += 10
    await ring.refresh()  # within the TTL: unchanged
    assert ring.openai().get_secret_value().endswith("1234")  # type: ignore[union-attr]
    now[0] += 30
    await ring.refresh()
    assert ring.openai().get_secret_value() == SECRET  # type: ignore[union-attr]
    await ring.refresh(force=True)
    assert ring.openai().get_secret_value() == SECRET  # type: ignore[union-attr]
```

- [ ] **Step 3: Run the tests and see them fail**

Run (in `backend/`): `uv run pytest tests/test_app_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.settings_store'`.

- [ ] **Step 4: Add `secrets_key` to Settings**

In `backend/app/core/config.py`, add the field below `openai_api_key` and a validator below `_secret_long_enough`:

```python
    secrets_key: SecretStr | None = None  # Fernet key encrypting API keys saved in Settings
```

```python
    @field_validator("secrets_key")
    @classmethod
    def _secrets_key_is_fernet(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            from cryptography.fernet import Fernet

            try:
                Fernet(value.get_secret_value().encode())
            except ValueError:
                raise ValueError(
                    "RAG_SECRETS_KEY must be a Fernet key: generate one with "
                    '`python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"`'
                ) from None
        return value
```

- [ ] **Step 5: Add the model and the migration**

`backend/app/settings_store/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    """Installation-wide settings edited in the admin console: one JSON value per key."""

    __tablename__ = "app_settings"
    __mapper_args__ = {"eager_defaults": True}

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None]
```

Add `from app.settings_store.models import AppSetting` to `backend/app/models.py`, and add `"AppSetting"` to `__all__` in alphabetical order.

`backend/migrations/versions/0008_app_settings.py`:

```python
"""app settings (branding, encrypted provider keys)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
```

Check the primary-key naming against `0007_evaluation.py`, and match how earlier migrations name primary keys if they differ.

- [ ] **Step 6: Write the service**

`backend/app/settings_store/service.py`:

```python
"""Installation settings: branding (name, color, logo) and the OpenAI key, encrypted with
RAG_SECRETS_KEY (Fernet). The key is never returned; only its last 4 characters are.
Functions flush; callers commit."""

import asyncio
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.storage import FileStore
from app.settings_store.models import AppSetting
from app.users.models import User

logger = logging.getLogger(__name__)

BRANDING = "branding"
OPENAI_KEY = "openai_api_key"
LOGO_PREFIX = "branding/"
LOGO_KEY = "branding/logo"
DEFAULT_APP_NAME = "Knowledge Assistant"
MAX_LOGO_BYTES = 512 * 1024
LOGO_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class SettingsError(Exception):
    code = "settings_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SecretsKeyMissing(SettingsError):
    code = "secrets_key_missing"


class InvalidLogo(SettingsError):
    code = "invalid_logo"


class Branding(BaseModel):
    app_name: str = Field(default=DEFAULT_APP_NAME, min_length=1, max_length=60)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class BrandingOut(Branding):
    logo_url: str | None = None


class KeyStatus(BaseModel):
    source: Literal["database", "environment", "none", "unreadable"]
    last4: str | None
    updated_at: datetime | None
    secrets_key_configured: bool


async def _value(session: AsyncSession, key: str) -> dict[str, Any]:
    row = await session.get(AppSetting, key)
    return dict(row.value) if row is not None else {}


async def _put(
    session: AsyncSession, key: str, value: dict[str, Any], actor: User | None
) -> AppSetting:
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        session.add(row)
    row.value = value
    row.updated_by = actor.id if actor is not None else None
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def get_branding(session: AsyncSession) -> BrandingOut:
    value = await _value(session, BRANDING)
    branding = Branding.model_validate(
        {k: value[k] for k in ("app_name", "primary_color") if k in value}
    )
    logo = value.get("logo")
    url = f"/api/branding/logo?v={logo['version']}" if logo else None
    return BrandingOut(**branding.model_dump(), logo_url=url)


async def update_branding(session: AsyncSession, actor: User, branding: Branding) -> BrandingOut:
    value = await _value(session, BRANDING)
    value.update(branding.model_dump())
    await _put(session, BRANDING, value, actor)
    await audit.record(
        session,
        action="settings.branding_updated",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
        detail=branding.model_dump(),
    )
    return await get_branding(session)


def _logo_type(data: bytes) -> str:
    if len(data) > MAX_LOGO_BYTES:
        raise InvalidLogo("The logo can be at most 512 KB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            image.verify()
    except Exception:
        raise InvalidLogo("The logo must be a PNG, JPEG or WebP image") from None
    if image_format not in LOGO_TYPES:
        raise InvalidLogo("The logo must be a PNG, JPEG or WebP image")
    return LOGO_TYPES[image_format]


async def set_logo(
    session: AsyncSession, store: FileStore, actor: User, data: bytes
) -> BrandingOut:
    content_type = _logo_type(data)
    await asyncio.to_thread(store.save, LOGO_KEY, data)
    value = await _value(session, BRANDING)
    value["logo"] = {"content_type": content_type, "version": uuid.uuid4().hex[:12]}
    await _put(session, BRANDING, value, actor)
    await audit.record(
        session,
        action="settings.logo_updated",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
        detail={"content_type": content_type, "bytes": len(data)},
    )
    return await get_branding(session)


async def clear_logo(session: AsyncSession, store: FileStore, actor: User) -> BrandingOut:
    value = await _value(session, BRANDING)
    value.pop("logo", None)
    await _put(session, BRANDING, value, actor)
    await asyncio.to_thread(store.delete_prefix, LOGO_PREFIX)
    await audit.record(
        session,
        action="settings.logo_removed",
        actor=actor,
        target_type="settings",
        target_id=BRANDING,
    )
    return await get_branding(session)


async def read_logo(session: AsyncSession, store: FileStore) -> tuple[bytes, str] | None:
    logo = (await _value(session, BRANDING)).get("logo")
    if not logo:
        return None
    try:
        data = await asyncio.to_thread(store.read, LOGO_KEY)
    except FileNotFoundError:
        return None
    return data, str(logo["content_type"])


def _fernet(settings: Settings) -> Fernet | None:
    if settings.secrets_key is None:
        return None
    return Fernet(settings.secrets_key.get_secret_value().encode())


def _decrypt(settings: Settings, token: str) -> str | None:
    fernet = _fernet(settings)
    if fernet is None:
        return None
    try:
        return fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None


async def openai_key_status(session: AsyncSession, settings: Settings) -> KeyStatus:
    configured = settings.secrets_key is not None
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None and row.value.get("ciphertext"):
        readable = _decrypt(settings, str(row.value["ciphertext"])) is not None
        return KeyStatus(
            source="database" if readable else "unreadable",
            last4=row.value.get("last4"),
            updated_at=row.updated_at,
            secrets_key_configured=configured,
        )
    if settings.openai_api_key is not None:
        return KeyStatus(
            source="environment",
            last4=settings.openai_api_key.get_secret_value()[-4:],
            updated_at=None,
            secrets_key_configured=configured,
        )
    return KeyStatus(source="none", last4=None, updated_at=None, secrets_key_configured=configured)


async def set_openai_key(
    session: AsyncSession, settings: Settings, actor: User, api_key: str
) -> KeyStatus:
    fernet = _fernet(settings)
    if fernet is None:
        raise SecretsKeyMissing(
            "Set RAG_SECRETS_KEY in deploy/.env and restart before saving API keys"
        )
    token = fernet.encrypt(api_key.encode()).decode()
    last4 = api_key[-4:]
    await _put(session, OPENAI_KEY, {"ciphertext": token, "last4": last4}, actor)
    await audit.record(
        session,
        action="settings.openai_key_set",
        actor=actor,
        target_type="settings",
        target_id=OPENAI_KEY,
        detail={"last4": last4},
    )
    return await openai_key_status(session, settings)


async def clear_openai_key(session: AsyncSession, settings: Settings, actor: User) -> KeyStatus:
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None:
        await session.delete(row)
        await session.flush()
    await audit.record(
        session,
        action="settings.openai_key_cleared",
        actor=actor,
        target_type="settings",
        target_id=OPENAI_KEY,
    )
    return await openai_key_status(session, settings)


async def resolve_openai_key(session: AsyncSession, settings: Settings) -> SecretStr | None:
    """The key provider calls use: the saved one if it decrypts, else RAG_OPENAI_API_KEY."""
    row = await session.get(AppSetting, OPENAI_KEY)
    if row is not None and row.value.get("ciphertext"):
        plain = _decrypt(settings, str(row.value["ciphertext"]))
        if plain is not None:
            return SecretStr(plain)
        logger.warning(
            "The saved OpenAI key can't be decrypted with RAG_SECRETS_KEY; "
            "using RAG_OPENAI_API_KEY instead"
        )
    return settings.openai_api_key
```

Check `LocalFileStore.read` for a missing key: if it raises something other than `FileNotFoundError`, catch that exception type instead.

- [ ] **Step 7: Write the KeyRing**

`backend/app/llm/keys.py`:

```python
"""The OpenAI key every provider call uses: the one saved in admin Settings, else
RAG_OPENAI_API_KEY. Re-read at most every `ttl` seconds so a rotation reaches every process
(API and workers) without a restart."""

import logging
import time
from collections.abc import Callable

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.settings_store.service import resolve_openai_key

logger = logging.getLogger(__name__)


class KeyRing:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        ttl: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._ttl = ttl
        self._clock = clock
        self._key = settings.openai_api_key
        self._loaded_at: float | None = None

    async def refresh(self, force: bool = False) -> None:
        now = self._clock()
        if not force and self._loaded_at is not None and now - self._loaded_at < self._ttl:
            return
        try:
            async with self._sessionmaker() as session:
                self._key = await resolve_openai_key(session, self._settings)
        except Exception:  # a database hiccup keeps the last known key
            logger.warning("Could not reload the OpenAI key", exc_info=True)
        self._loaded_at = now

    def openai(self) -> SecretStr | None:
        return self._key

    def use_settings(self, settings: Settings) -> None:
        """Follow the app's live settings (tests swap them; production never does)."""
        self._settings = settings
```

- [ ] **Step 8: Let the gateway take an explicit key**

In `backend/app/llm/gateway.py`, replace `_api_key` and add `api_key: SecretStr | None = None` as the **last** parameter of `get_embeddings`, `get_vision_model`, `get_chat_model` and `get_moderator`. Pass it on as `_api_key(settings, api_key)`:

```python
def _api_key(settings: Settings, override: SecretStr | None = None) -> SecretStr:
    key = override or settings.openai_api_key
    if key is None:
        raise RuntimeError(
            "No OpenAI API key: save one in admin Settings or set RAG_OPENAI_API_KEY"
        )
    return key
```

For example, `get_chat_model(settings, model, api_key=None)` creates `ChatOpenAI(model=model, api_key=_api_key(settings, api_key), ...)`. `get_moderator(settings, client=None, api_key=None)` keeps its existing `client` parameter.

In `backend/app/evaluation/scoring.py`, give `build_ragas_scorer(settings, judge_model, api_key: SecretStr | None = None)` this body for the key:

```python
    key = api_key or settings.openai_api_key
    if key is None:
        raise RuntimeError("No OpenAI API key: save one in admin Settings or set RAG_OPENAI_API_KEY")
    client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=2, timeout=120)
```

(Import `SecretStr` from pydantic.)

- [ ] **Step 9: Wire the KeyRing**

Replace `backend/app/chat/wiring.py`'s `build_chat_deps` with:

```python
def build_chat_deps(settings: Settings, index: ChunkIndex, keys: KeyRing | None = None) -> ChatDeps:
    """Real providers, created on first use so the app starts without API keys. Clients are
    cached per API key, so a key saved in admin Settings takes effect on the next refresh."""

    def current_key() -> str | None:
        key = keys.openai() if keys is not None else None
        return key.get_secret_value() if key is not None else None

    def secret(key: str | None) -> SecretStr | None:
        return SecretStr(key) if key is not None else None

    @lru_cache(maxsize=2)
    def embeddings(key: str | None) -> Embeddings:
        return get_embeddings(settings, api_key=secret(key))

    async def embed_query(text: str) -> list[float]:
        return await embeddings(current_key()).aembed_query(text)

    @lru_cache(maxsize=16)
    def cached_chat_model(name: str, key: str | None) -> BaseChatModel:
        return get_chat_model(settings, name, api_key=secret(key))

    def chat_model(name: str) -> BaseChatModel:
        return cached_chat_model(name, current_key())

    @lru_cache(maxsize=2)
    def moderator(key: str | None) -> Callable[[str], Awaitable[dict[str, bool]]]:
        return get_moderator(settings, api_key=secret(key))

    async def moderate(text: str) -> dict[str, bool]:
        return await moderator(current_key())(text)

    return ChatDeps(
        retrieval=RetrievalDeps(index=index, embed_query=embed_query, rerank=rerank),
        chat_model=chat_model,
        moderate=moderate,
    )
```

Add the imports: `from pydantic import SecretStr` and `from app.llm.keys import KeyRing`.

`backend/app/main.py`:
- Import `from app.llm.keys import KeyRing`.
- After `app.state.sessionmaker = ...`, add `app.state.keys = KeyRing(settings, app.state.sessionmaker)`.
- Change the deps line to `app.state.chat_deps = build_chat_deps(settings, app.state.index, app.state.keys)`.

`backend/app/api/chat.py`, in `chat()`, as the first line of the body:

```python
    await request.app.state.keys.refresh()  # picks up a key rotated in admin Settings
```

`backend/app/ingestion/tasks.py`:
- Give `build_deps` an extra last parameter `api_key: SecretStr | None = None`, and pass it as `get_embeddings(settings, api_key=api_key)` and `get_vision_model(settings, api_key=api_key)`.
- In `_run`:

```python
    try:
        sessionmaker = create_sessionmaker(engine)
        keys = KeyRing(settings, sessionmaker)
        await keys.refresh(force=True)
        deps = build_deps(settings, sessionmaker, qdrant, api_key=keys.openai())
        return await run_ingestion(version_id, deps, final_attempt=final_attempt)
```

`backend/app/evaluation/tasks.py`, in `_run`:

```python
    try:
        index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimensions)
        sessionmaker = create_sessionmaker(engine)
        keys = KeyRing(settings, sessionmaker)
        await keys.refresh(force=True)
        await execute_run(
            run_id,
            sessionmaker=sessionmaker,
            deps=build_chat_deps(settings, index, keys),
            scorer_factory=lambda judge: build_ragas_scorer(settings, judge, keys.openai()),
        )
```

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_app_settings.py tests/test_index_and_gateway.py tests/test_guardrails_input.py tests/test_chat_api.py -q`
Expected: PASS. `test_embeddings_require_api_key` still matches `RAG_OPENAI_API_KEY`.

Then run the full suite and ruff: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 11: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/app/settings_store backend/app/llm/keys.py backend/app/llm/gateway.py backend/app/chat/wiring.py backend/app/main.py backend/app/api/chat.py backend/app/ingestion/tasks.py backend/app/evaluation/tasks.py backend/app/evaluation/scoring.py backend/app/models.py backend/migrations/versions/0008_app_settings.py backend/tests/test_app_settings.py
git commit -m "feat(settings): encrypted OpenAI key and branding store with a refreshing key ring"
```

---

### Task 2: Branding and Settings API

**Files:**
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/api/router.py`, `backend/tests/test_auth.py` (PUBLIC_ROUTES)
- Test: `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: Task 1's `settings_store.service` and `app.state.keys`; `ensure_password_confirmed`; `SuperAdminUser`; `PasswordConfirm` (`app.documents.schemas`).
- Produces (the frontend relies on these):
  - `GET /api/branding` (public) returns `{app_name, primary_color, logo_url}`.
  - `GET /api/branding/logo` (public) returns the image bytes with its content type, `Cache-Control: public, max-age=300` and `X-Content-Type-Options: nosniff`, or 404 `not_found`.
  - `PUT /api/admin/settings/branding` takes `{app_name, primary_color}` and returns BrandingOut.
  - `POST /api/admin/settings/branding/logo` takes a multipart `file` and returns BrandingOut, or 422 `invalid_logo`.
  - `DELETE /api/admin/settings/branding/logo` returns BrandingOut.
  - `GET /api/admin/settings/openai-key` returns KeyStatus.
  - `PUT /api/admin/settings/openai-key` takes `{api_key, password}` and returns KeyStatus. Errors: 403 `password_confirmation_failed`, 409 `secrets_key_missing`.
  - `POST /api/admin/settings/openai-key/clear` takes `{password}` and returns KeyStatus.
  - All `/api/admin/settings/*` routes are super_admin only.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_settings_api.py`:

```python
import io

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import Role
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

SECRET = "sk-live-abcdefghijklmnop9876"


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


async def _root(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    return bearer(await login(client, "root"))


@pytest.fixture
def with_secrets_key(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"secrets_key": SecretStr(Fernet.generate_key().decode())}
    )


async def test_settings_are_super_admin_only(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="admin1", role=Role.ADMIN)
    headers = bearer(await login(client, "admin1"))
    for method, path in [
        ("GET", "/api/admin/settings/openai-key"),
        ("PUT", "/api/admin/settings/branding"),
    ]:
        response = await client.request(method, path, headers=headers, json={})
        assert response.status_code == 403, path


async def test_branding_roundtrip_is_public(client: AsyncClient, session: AsyncSession) -> None:
    headers = await _root(client, session)
    assert (await client.get("/api/branding")).json() == {
        "app_name": "Knowledge Assistant",
        "primary_color": None,
        "logo_url": None,
    }
    bad = await client.put(
        "/api/admin/settings/branding",
        headers=headers,
        json={"app_name": "Acme", "primary_color": "red; background:url(x)"},
    )
    assert bad.status_code == 422
    saved = await client.put(
        "/api/admin/settings/branding",
        headers=headers,
        json={"app_name": "Acme", "primary_color": "#0F766E"},
    )
    assert saved.status_code == 200
    assert (await client.get("/api/branding")).json()["primary_color"] == "#0F766E"


async def test_logo_rejects_non_images_and_svg(client: AsyncClient, session: AsyncSession) -> None:
    headers = await _root(client, session)
    for name, data in [("x.svg", b"<svg onload=alert(1)/>"), ("x.png", b"<html></html>")]:
        response = await client.post(
            "/api/admin/settings/branding/logo",
            headers=headers,
            files={"file": (name, data, "image/png")},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_logo"
    assert (await client.get("/api/branding/logo")).status_code == 404

    uploaded = await client.post(
        "/api/admin/settings/branding/logo",
        headers=headers,
        files={"file": ("logo.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200
    logo = await client.get(uploaded.json()["logo_url"])
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.headers["x-content-type-options"] == "nosniff"
    assert logo.content == _png()

    removed = await client.delete("/api/admin/settings/branding/logo", headers=headers)
    assert removed.json()["logo_url"] is None


async def test_openai_key_endpoints_never_echo_the_key(
    app: FastAPI, client: AsyncClient, session: AsyncSession, with_secrets_key: None
) -> None:
    headers = await _root(client, session)
    wrong = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": "wrong-password-1"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["code"] == "password_confirmation_failed"

    saved = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": DEFAULT_PASSWORD},
    )
    assert saved.status_code == 200
    assert saved.json()["source"] == "database"
    assert saved.json()["last4"] == "9876"
    assert SECRET not in saved.text
    assert app.state.keys.openai().get_secret_value() == SECRET  # refreshed at once

    status = await client.get("/api/admin/settings/openai-key", headers=headers)
    assert SECRET not in status.text
    audit = await client.get("/api/admin/audit", headers=headers)
    assert SECRET not in audit.text

    cleared = await client.post(
        "/api/admin/settings/openai-key/clear",
        headers=headers,
        json={"password": DEFAULT_PASSWORD},
    )
    assert cleared.json()["source"] == "none"


async def test_saving_a_key_without_secrets_key_is_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _root(client, session)
    response = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "secrets_key_missing"
```

The `with_secrets_key` fixture swaps `app.state.settings`, while `app.state.keys` was built with the original settings. So after a save, the route calls `keys.use_settings(settings)` (Task 1) with the live settings, then `refresh(force=True)`. It updates the existing ring rather than replacing it, because `chat_deps` holds a reference to that same object.

- [ ] **Step 2: Add the public routes to the auth test**

In `backend/tests/test_auth.py`, extend `PUBLIC_ROUTES`:

```python
    ("GET", "/api/branding"),
    ("GET", "/api/branding/logo"),
```

- [ ] **Step 3: Implement the routes**

`backend/app/api/settings.py`:

```python
"""Branding (public, so the sign-in page can show it) and installation settings
(super_admin). Saving or clearing the API key needs password re-entry and is audited."""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.errors import api_error
from app.auth.deps import SessionDep, SettingsDep, SuperAdminUser, ensure_password_confirmed
from app.core.storage import FileStore
from app.documents.schemas import PasswordConfirm
from app.llm.keys import KeyRing
from app.settings_store import service
from app.settings_store.service import Branding, BrandingOut, KeyStatus

public_router = APIRouter(tags=["branding"])
router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

_STATUS = {service.SecretsKeyMissing: 409, service.InvalidLogo: 422}


class OpenAIKeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=300, pattern=r"^\S+$")
    password: str = Field(min_length=1, max_length=128)


def _http_error(exc: service.SettingsError) -> HTTPException:
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


def _store(request: Request) -> FileStore:
    store: FileStore = request.app.state.store
    return store


async def _reload_keys(request: Request, settings: Settings) -> None:
    """Apply a saved or cleared key now. Updates the shared ring that chat_deps holds."""
    keys: KeyRing = request.app.state.keys
    keys.use_settings(settings)
    await keys.refresh(force=True)


@public_router.get("/branding")
async def get_branding(session: SessionDep) -> BrandingOut:
    return await service.get_branding(session)


@public_router.get("/branding/logo")
async def get_logo(session: SessionDep, request: Request) -> Response:
    logo = await service.read_logo(session, _store(request))
    if logo is None:
        raise api_error(404, "not_found", "No logo is set")
    data, content_type = logo
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/branding")
async def update_branding(
    body: Branding, user: SuperAdminUser, session: SessionDep
) -> BrandingOut:
    branding = await service.update_branding(session, user, body)
    await session.commit()
    return branding


@router.post("/branding/logo")
async def upload_logo(
    user: SuperAdminUser,
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> BrandingOut:
    data = await file.read(service.MAX_LOGO_BYTES + 1)
    try:
        branding = await service.set_logo(session, _store(request), user, data)
    except service.SettingsError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return branding


@router.delete("/branding/logo")
async def remove_logo(user: SuperAdminUser, session: SessionDep, request: Request) -> BrandingOut:
    branding = await service.clear_logo(session, _store(request), user)
    await session.commit()
    return branding


@router.get("/openai-key")
async def key_status(_: SuperAdminUser, session: SessionDep, settings: SettingsDep) -> KeyStatus:
    return await service.openai_key_status(session, settings)


@router.put("/openai-key")
async def set_key(
    body: OpenAIKeyIn,
    user: SuperAdminUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> KeyStatus:
    await ensure_password_confirmed(user, body.password)
    try:
        status = await service.set_openai_key(session, settings, user, body.api_key)
    except service.SettingsError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await _reload_keys(request, settings)
    return status


@router.post("/openai-key/clear")
async def clear_key(
    body: PasswordConfirm,
    user: SuperAdminUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> KeyStatus:
    await ensure_password_confirmed(user, body.password)
    status = await service.clear_openai_key(session, settings, user)
    await session.commit()
    await _reload_keys(request, settings)
    return status
```

Add `from app.core.config import Settings` to the imports.

In `backend/app/api/router.py`, import `settings` (it's a module, so alias it: `from app.api import settings as settings_api`), then add:

```python
api_router.include_router(settings_api.public_router)
api_router.include_router(settings_api.router)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_settings_api.py tests/test_auth.py -q`
Expected: PASS. The "every admin route requires admin" check gets 403 from the super_admin routes.

Then: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/settings.py backend/app/api/router.py backend/tests/test_settings_api.py backend/tests/test_auth.py
git commit -m "feat(api): public branding and super-admin settings endpoints"
```

---

### Task 3: Dashboard, audit filters and CSV export, trace id in review

**Files:**
- Create: `backend/app/dashboard/__init__.py` (empty), `backend/app/dashboard/service.py`, `backend/app/api/admin_dashboard.py`
- Modify: `backend/app/audit/service.py`, `backend/app/audit/schemas.py`, `backend/app/api/admin.py`, `backend/app/api/router.py`, `backend/app/evaluation/schemas.py`
- Test: `backend/tests/test_dashboard_audit.py`

**Interfaces:**
- Consumes:
  - the models `Message`, `Conversation` (`app.chat.models`) and `UsageRecord`, `GuardrailEvent` (`app.guardrails.models`);
  - `documents.service.status_counts(session)`;
  - `app.state.index.client` (AsyncQdrantClient) and `app.state.rate_limiter.redis`.
- Produces:
  - `GET /api/admin/dashboard?days=7|30|90` (admin) returns:
    `{days, totals: {questions, active_users, input_tokens, output_tokens, cost_usd, thumbs_up_rate, not_found_rate, low_confidence_rate, guardrail_blocks}, daily: [{date, questions, cost_usd, not_found, low_confidence, blocked}], ingestion: {status: count}, health: {database, qdrant, redis}}`.
    Rates are 0–1 or `null` when there's nothing to divide by. `daily` is zero-filled and has exactly `days` items, oldest first.
  - `GET /api/admin/audit?actor=&action=&target_type=&target_id=&since=&until=&before_id=&limit=` (admin) returns `AuditEntryOut[]`, newest first. `AuditEntryOut` gains `request_id`.
  - `GET /api/admin/audit/export` with the same filters (no paging) returns `text/csv` as an attachment.
  - `ReviewAnswer` gains `trace_id: str | None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dashboard_audit.py`:

```python
import csv
import io
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.chat.models import Conversation, Message
from app.dashboard import service as dashboard
from app.guardrails.models import GuardrailEvent, UsageRecord
from app.users.models import Role
from tests.factories import bearer, login, make_user

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


async def _answer(
    session: AsyncSession, conversation: Conversation, when: datetime, **fields: object
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="a",
        created_at=when,
        **fields,
    )
    session.add(message)
    await session.flush()
    return message


async def test_dashboard_summary(session: AsyncSession) -> None:
    alice = await make_user(session, username="alice")
    bob = await make_user(session, username="bob")
    c1 = Conversation(user_id=alice.id, title="t")
    c2 = Conversation(user_id=bob.id, title="t")
    session.add_all([c1, c2])
    await session.flush()
    today, yesterday = NOW, NOW - timedelta(days=1)
    await _answer(session, c1, today, outcome="answered", feedback_rating=1)
    await _answer(session, c1, today, outcome="answered", low_confidence=True, feedback_rating=-1)
    await _answer(session, c2, yesterday, outcome="not_found", feedback_rating=1)
    await _answer(session, c2, yesterday, outcome="blocked")
    await _answer(session, c2, NOW - timedelta(days=20), outcome="answered")  # outside 7 days
    session.add_all(
        [
            UsageRecord(user_id=alice.id, input_tokens=100, output_tokens=50, cost_usd=0.5,
                        created_at=today),
            UsageRecord(user_id=bob.id, input_tokens=10, output_tokens=5, cost_usd=0.25,
                        created_at=yesterday),
            GuardrailEvent(user_id=bob.id, check="moderation", action="blocked",
                           created_at=yesterday),
            GuardrailEvent(user_id=bob.id, check="moderation", action="flagged",
                           created_at=yesterday),
        ]
    )
    await session.commit()

    totals, daily = await dashboard.summary(session, days=7, now=NOW)

    assert totals.questions == 4
    assert totals.active_users == 2
    assert (totals.input_tokens, totals.output_tokens) == (110, 55)
    assert totals.cost_usd == 0.75
    assert totals.thumbs_up_rate == 2 / 3
    assert totals.not_found_rate == 1 / 4
    assert totals.low_confidence_rate == 1 / 2  # of answered
    assert totals.guardrail_blocks == 1
    assert len(daily) == 7
    assert daily[0].date.isoformat() == "2026-10-02"
    assert (daily[-1].questions, daily[-1].low_confidence, daily[-1].cost_usd) == (2, 1, 0.5)
    assert (daily[-2].questions, daily[-2].not_found, daily[-2].blocked) == (2, 1, 1)


async def test_empty_dashboard_has_null_rates(session: AsyncSession) -> None:
    totals, daily = await dashboard.summary(session, days=30, now=NOW)
    assert totals.questions == 0
    assert totals.thumbs_up_rate is None and totals.not_found_rate is None
    assert len(daily) == 30 and all(d.questions == 0 for d in daily)


async def test_dashboard_api(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="admin1", role=Role.ADMIN)
    headers = bearer(await login(client, "admin1"))
    response = await client.get("/api/admin/dashboard?days=7", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["daily"]) == 7
    assert body["health"]["database"] == "ok"
    assert set(body["health"]) == {"database", "qdrant", "redis"}
    assert "ready" in body["ingestion"]
    assert (await client.get("/api/admin/dashboard?days=5", headers=headers)).status_code == 422


async def test_audit_filters_and_paging(client: AsyncClient, session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    headers = bearer(await login(client, "admin1"))  # writes auth.login entries
    for i in range(3):
        await audit.record(session, action="user.created", actor=admin, target_type="user",
                           target_id=f"u{i}")
    await audit.record(session, action="document.deleted", actor=admin)
    await session.commit()

    users = await client.get("/api/admin/audit?action=user.&limit=2", headers=headers)
    rows = users.json()
    assert [r["target_id"] for r in rows] == ["u2", "u1"]
    assert "request_id" in rows[0]
    older = await client.get(
        f"/api/admin/audit?action=user.&before_id={rows[-1]['id']}", headers=headers
    )
    assert [r["target_id"] for r in older.json()] == ["u0"]
    by_actor = await client.get("/api/admin/audit?actor=ADMIN1&action=document.", headers=headers)
    assert [r["action"] for r in by_actor.json()] == ["document.deleted"]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    none = await client.get("/api/admin/audit", params={"since": future}, headers=headers)
    assert none.json() == []


async def test_audit_export_is_csv_safe_and_audited(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="admin1", role=Role.ADMIN)
    headers = bearer(await login(client, "admin1"))
    await audit.record(session, action="user.created", target_id="=HYPERLINK(\"http://x\")",
                       detail={"note": "+1"})
    await session.commit()

    response = await client.get("/api/admin/audit/export?action=user.", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:5] == ["id", "created_at", "actor_username", "actor_id", "action"]
    target = rows[1][rows[0].index("target_id")]
    assert target.startswith("'=")

    log = await client.get("/api/admin/audit?action=audit.exported", headers=headers)
    assert log.json()[0]["detail"]["filters"]["action"] == "user."
```

Factory constructor arguments for `UsageRecord` and `GuardrailEvent` are shown multi-line. Format with `ruff format` after writing. If `GuardrailEvent` or `UsageRecord` require other non-null columns, add them with neutral values. Check `app/guardrails/models.py` first.

- [ ] **Step 2: Run the tests and see them fail**

Run: `uv run pytest tests/test_dashboard_audit.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.dashboard'`.

- [ ] **Step 3: Dashboard service**

`backend/app/dashboard/service.py`:

```python
"""Admin dashboard figures, computed live from Postgres over whole UTC days (spec §6.5)."""

from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation, Message
from app.guardrails.models import GuardrailEvent, UsageRecord


class Totals(BaseModel):
    questions: int
    active_users: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    thumbs_up_rate: float | None
    not_found_rate: float | None
    low_confidence_rate: float | None
    guardrail_blocks: int


class DailyPoint(BaseModel):
    date: date
    questions: int = 0
    cost_usd: float = 0.0
    not_found: int = 0
    low_confidence: int = 0
    blocked: int = 0


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _day(column: object) -> object:
    return cast(func.timezone("UTC", column), Date)


async def summary(
    session: AsyncSession, days: int, now: datetime | None = None
) -> tuple[Totals, list[DailyPoint]]:
    now = now or datetime.now(UTC)
    first = (now - timedelta(days=days - 1)).date()
    since = datetime.combine(first, time.min, tzinfo=UTC)
    answers = (Message.role == "assistant") & (Message.created_at >= since)

    day = _day(Message.created_at).label("day")
    per_day = await session.execute(
        select(
            day,
            func.count(),
            func.count().filter(Message.outcome == "not_found"),
            func.count().filter(Message.low_confidence.is_(True)),
            func.count().filter(Message.outcome == "blocked"),
        )
        .where(answers)
        .group_by(day)
    )
    points = {first + timedelta(days=i): DailyPoint(date=first + timedelta(days=i))
              for i in range(days)}
    for when, questions, not_found, low, blocked in per_day.all():
        if when in points:
            point = points[when]
            point.questions, point.not_found = questions, not_found
            point.low_confidence, point.blocked = low, blocked

    cost_day = _day(UsageRecord.created_at).label("day")
    for when, cost in (
        await session.execute(
            select(cost_day, func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
            .where(UsageRecord.created_at >= since)
            .group_by(cost_day)
        )
    ).all():
        if when in points:
            points[when].cost_usd = round(float(cost), 6)

    counts = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Message.outcome == "answered"),
                func.count().filter(Message.outcome == "not_found"),
                func.count().filter(
                    (Message.outcome == "answered") & Message.low_confidence.is_(True)
                ),
                func.count().filter(Message.feedback_rating == 1),
                func.count().filter(Message.feedback_rating.is_not(None)),
                func.count(func.distinct(Conversation.user_id)),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(answers)
        )
    ).one()
    questions, answered, not_found, low, thumbs_up, rated, active = counts
    usage = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
            ).where(UsageRecord.created_at >= since)
        )
    ).one()
    blocks = await session.scalar(
        select(func.count()).where(
            GuardrailEvent.action == "blocked", GuardrailEvent.created_at >= since
        )
    )
    totals = Totals(
        questions=questions,
        active_users=active,
        input_tokens=int(usage[0]),
        output_tokens=int(usage[1]),
        cost_usd=round(float(usage[2]), 6),
        thumbs_up_rate=_rate(thumbs_up, rated),
        not_found_rate=_rate(not_found, questions),
        low_confidence_rate=_rate(low, answered),
        guardrail_blocks=blocks or 0,
    )
    return totals, [points[d] for d in sorted(points)]
```

Run `ruff format` afterwards; the dict comprehension spans lines.

- [ ] **Step 4: Dashboard route**

`backend/app/api/admin_dashboard.py`:

```python
"""Admin dashboard (spec §6.5): usage, quality and ingestion figures plus service health."""

import asyncio
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.dashboard import service
from app.documents import service as documents

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])
PERIODS = (7, 30, 90)


class DashboardOut(BaseModel):
    days: int
    totals: service.Totals
    daily: list[service.DailyPoint]
    ingestion: dict[str, int]
    health: dict[str, str]


async def _probe(check: Awaitable[Any]) -> str:
    try:
        async with asyncio.timeout(2):
            await check
    except Exception:
        return "error"
    return "ok"


@router.get("")
async def get_dashboard(
    _: AdminUser, session: SessionDep, request: Request, days: int = 30
) -> DashboardOut:
    if days not in PERIODS:
        raise api_error(422, "invalid_days", "days must be 7, 30 or 90")
    totals, daily = await service.summary(session, days)
    health = {
        "database": "ok",  # the queries above succeeded
        "qdrant": await _probe(request.app.state.index.client.get_collections()),
        "redis": await _probe(request.app.state.rate_limiter.redis.ping()),
    }
    return DashboardOut(
        days=days,
        totals=totals,
        daily=daily,
        ingestion=await documents.status_counts(session),
        health=health,
    )
```

Register it in `router.py`: `from app.api import admin_dashboard` and `api_router.include_router(admin_dashboard.router)`.

- [ ] **Step 5: Audit filters and export**

Add to `backend/app/audit/schemas.py`, as the last field of `AuditEntryOut`:

```python
    request_id: str | None = None
```

And add a filters model:

```python
class AuditFilters(BaseModel):
    actor: str | None = Field(default=None, max_length=64)  # username, case-insensitive
    action: str | None = Field(default=None, max_length=100)  # prefix, e.g. "user."
    target_type: str | None = Field(default=None, max_length=50)
    target_id: str | None = Field(default=None, max_length=100)
    since: datetime | None = None
    until: datetime | None = None
```

(Import `Field`.)

Append to `backend/app/audit/service.py`:

```python
CSV_COLUMNS = [
    "id",
    "created_at",
    "actor_username",
    "actor_id",
    "action",
    "target_type",
    "target_id",
    "request_id",
    "detail",
]
MAX_EXPORT_ROWS = 100_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _filtered(filters: AuditFilters) -> Select[tuple[AuditLog]]:
    query = select(AuditLog)
    if filters.actor:
        query = query.where(func.lower(AuditLog.actor_username) == filters.actor.strip().lower())
    if filters.action:
        query = query.where(AuditLog.action.startswith(filters.action.strip(), autoescape=True))
    if filters.target_type:
        query = query.where(AuditLog.target_type == filters.target_type)
    if filters.target_id:
        query = query.where(AuditLog.target_id == filters.target_id)
    if filters.since:
        query = query.where(AuditLog.created_at >= filters.since)
    if filters.until:
        query = query.where(AuditLog.created_at < filters.until)
    return query


async def search(
    session: AsyncSession, filters: AuditFilters, *, before_id: int | None, limit: int
) -> list[AuditLog]:
    query = _filtered(filters)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    query = query.order_by(AuditLog.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


def csv_line(values: Sequence[object]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow([_cell(v) for v in values])
    return buffer.getvalue()


async def export_lines(session: AsyncSession, filters: AuditFilters) -> AsyncIterator[str]:
    """CSV lines (header first), newest first, at most MAX_EXPORT_ROWS rows."""
    yield csv_line(CSV_COLUMNS)
    query = _filtered(filters).order_by(AuditLog.id.desc()).limit(MAX_EXPORT_ROWS)
    rows = await session.stream_scalars(query.execution_options(yield_per=1000))
    async for entry in rows:
        yield csv_line(
            [
                entry.id,
                entry.created_at.isoformat(),
                entry.actor_username,
                entry.actor_id,
                entry.action,
                entry.target_type,
                entry.target_id,
                entry.request_id,
                json.dumps(entry.detail, sort_keys=True, default=str),
            ]
        )
```

Add the imports `csv`, `io`, `json`, `from collections.abc import AsyncIterator, Sequence`, `from sqlalchemy import Select, func, select` and `from app.audit.schemas import AuditFilters`. The `record` signature stays as it is.

In `backend/app/api/admin.py`, replace `list_audit` with:

```python
@router.get("/audit")
async def list_audit(
    _: AdminUser,
    session: SessionDep,
    filters: Annotated[AuditFilters, Query()],
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEntryOut]:
    entries = await audit.search(session, filters, before_id=before_id, limit=limit)
    return [AuditEntryOut.model_validate(e) for e in entries]


@router.get("/audit/export")
async def export_audit(
    admin: AdminUser,
    session: SessionDep,
    request: Request,
    filters: Annotated[AuditFilters, Query()],
) -> StreamingResponse:
    await audit.record(
        session,
        action="audit.exported",
        actor=admin,
        detail={"filters": filters.model_dump(mode="json", exclude_none=True)},
    )
    await session.commit()
    sessionmaker = request.app.state.sessionmaker

    async def lines() -> AsyncIterator[str]:
        async with sessionmaker() as export_session:  # outlives the request's session
            async for line in audit.export_lines(export_session, filters):
                yield line

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        lines(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )
```

Add the imports `Request` (fastapi), `StreamingResponse` (`fastapi.responses`), `AsyncIterator`, `datetime`/`UTC`, and `AuditFilters` (from `app.audit.schemas`). The existing `list_recent` stays for other callers. Grep its users; if there are none, delete it.

- [ ] **Step 6: Trace id in review detail**

In `backend/app/evaluation/schemas.py`, add `trace_id: str | None = None` to `ReviewAnswer` after `feedback_comment`. `Message.trace_id` already exists, so `from_attributes` fills it.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_dashboard_audit.py tests/test_auth.py tests/test_review_queue.py tests/test_admin_api.py -q`
Expected: PASS.

Then: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

- [ ] **Step 8: Commit**

```bash
git add backend/app/dashboard backend/app/api/admin_dashboard.py backend/app/api/router.py backend/app/audit backend/app/api/admin.py backend/app/evaluation/schemas.py backend/tests/test_dashboard_audit.py
git commit -m "feat(admin): dashboard figures, audit filters with csv export, trace id in review"
```

---
### Task 4: Admin shell — gate, sidebar, branding, shared admin components and API client

**Files:**
- Add with the shadcn CLI: `frontend/components/ui/{table,tabs,native-select,switch,checkbox,chart}.tsx`
- Modify: `frontend/package.json`, `frontend/package-lock.json` (`@tanstack/react-table`, plus `recharts` from `chart`)
- Modify: `frontend/lib/types.ts`, `frontend/lib/api.ts` (`branding`)
- Create: `frontend/lib/admin-api.ts`, `frontend/lib/roles.ts`, `frontend/lib/branding.ts`, `frontend/lib/format.ts`
- Create: `frontend/components/me-gate.tsx`, `frontend/components/branding.tsx`
- Create: `frontend/components/admin/admin-sidebar.tsx`, `data-table.tsx`, `password-dialog.tsx`, `page-header.tsx`, `super-admin-only.tsx`, `group-checklist.tsx`
- Create: `frontend/app/admin/layout.tsx`
- Modify: `frontend/app/app/layout.tsx` (use MeGate), `frontend/proxy.ts`, `frontend/components/providers.tsx`, `frontend/components/user-menu.tsx`, `frontend/components/app-sidebar.tsx`, `frontend/components/auth/auth-layout.tsx`
- Test: `frontend/lib/branding.test.ts`, `frontend/lib/format.test.ts`, `frontend/app/admin/layout.test.tsx`, `frontend/components/admin/admin-sidebar.test.tsx`, `frontend/components/admin/password-dialog.test.tsx`

**Interfaces:**
- Consumes: from Plan 6, `apiJson`, `apiFetch`, `ApiError`, `api.me`, `renderWithProviders`, `jsonResponse` and the `["me"]` query key. From Tasks 1–3, the backend routes.
- Produces (Tasks 5–12 use these):
  - **Types** in `lib/types.ts` (below).
  - **`adminApi`** in `lib/admin-api.ts` (below), plus `api.branding()`.
  - **`lib/roles.ts`:** `isAdmin(user)` and `isSuperAdmin(user)`.
  - **`lib/format.ts`:** `formatDateTime(iso)`, `formatPercent(rate | null)` (`"—"` for null), `formatUsd(n)`, `formatBytes(n)`.
  - **`lib/branding.ts`:** `contrastText(hex)` and `useBranding() -> {appName, primaryColor, logoUrl}`.
  - **`components/branding.tsx`:** `BrandingEffect` and `BrandMark({className?})`.
  - **`components/me-gate.tsx`:** `MeGate({allow?, redirectTo?, children})`.
  - **`components/admin/*` shared components:**
    - `DataTable<T>({columns, data, isLoading?, empty?, getRowId?})`
    - `PasswordDialog({open, onOpenChange, title, description, confirmLabel?, destructive?, onConfirm(password) => Promise<unknown>})`
    - `PageHeader({title, description?, actions?})`
    - `SuperAdminOnly({children})`
    - `GroupChecklist({groups, value, onChange, idPrefix, empty?})`
  - **Query keys:** everything admin starts with `["admin", ...]`. Invalidating `["admin", "<area>"]` refreshes that area.

- [ ] **Step 1: Add the components and libraries**

Run (in `frontend/`):

```bash
npx shadcn@4.21.4 add table tabs native-select switch checkbox chart
npm install @tanstack/react-table@^8
```

Expected: the new files are in `components/ui/`, and `recharts` and `@tanstack/react-table` are in `package.json`. If the registry has no `native-select`, write `components/ui/native-select.tsx` yourself as a styled native `<select>` (`NativeSelect`) with `NativeSelectOption`, using the `Input` classes for styling. Then `npm run lint && npm run typecheck`.

- [ ] **Step 2: Add the admin types**

Append to `frontend/lib/types.ts`:

```ts
// ---- Admin console (mirrors backend admin schemas) ----

export interface AdminUser extends User {
  locked_until: string | null
  chat_locked_until: string | null
  created_at: string
}

export interface UserCreate {
  username: string
  full_name: string
  password: string
  role: Role
  group_ids: string[]
}

export interface UserUpdate {
  full_name?: string
  role?: Role
  group_ids?: string[]
  is_active?: boolean
  unlock?: boolean
}

export interface AdminCollection extends Collection {
  sensitive: boolean
  groups: Group[]
  created_at: string
}

export interface CollectionInput {
  name: string
  description: string
  sensitive: boolean
  group_ids: string[]
}

export interface CollectionUpdate {
  name?: string
  description?: string
  sensitive?: boolean
  group_ids?: string[]
  password?: string
}

export type VersionStatus =
  | "queued"
  | "scanning"
  | "parsing"
  | "enriching"
  | "chunking"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed"
  | "rejected"

export interface DocumentVersion {
  id: string
  version_no: number
  status: VersionStatus
  failed_stage: string | null
  error: string | null
  chunk_count: number
  page_count: number | null
  content_type: string
  size_bytes: number
  created_at: string
  updated_at: string
}

export interface AdminDocument {
  id: string
  collection_id: string
  filename: string
  current_version_id: string | null
  deleted_at: string | null
  restricted_groups: Group[]
  versions: DocumentVersion[]
  created_at: string
}

export interface UploadResult {
  filename: string
  outcome: "queued" | "duplicate" | "invalid"
  message: string
  document_id: string | null
  version_id: string | null
}

export interface Chunk {
  position: number
  text: string
  modality: string
  page: number | null
  heading_path: string[]
  extra: Record<string, unknown>
}

export interface AdminNotification {
  id: string
  kind: string
  title: string
  body: string
  target_type: string | null
  target_id: string | null
  created_at: string
  read_at: string | null
}

export interface DailyPoint {
  date: string
  questions: number
  cost_usd: number
  not_found: number
  low_confidence: number
  blocked: number
}

export interface Dashboard {
  days: number
  totals: {
    questions: number
    active_users: number
    input_tokens: number
    output_tokens: number
    cost_usd: number
    thumbs_up_rate: number | null
    not_found_rate: number | null
    low_confidence_rate: number | null
    guardrail_blocks: number
  }
  daily: DailyPoint[]
  ingestion: Record<string, number>
  health: Record<string, string>
}

export interface AuditEntry {
  id: number
  created_at: string
  actor_id: string | null
  actor_username: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown>
  request_id: string | null
}

export interface AuditFilters {
  actor?: string
  action?: string
  target_type?: string
  target_id?: string
  since?: string
  until?: string
}

export type ReviewKind = "feedback" | "low_confidence" | "guardrail"

export interface ReviewItem {
  kind: ReviewKind
  id: string
  created_at: string
  user_id: string
  username: string
  message_id: string | null
  question: string | null
  answer: string | null
  detail: Record<string, unknown>
  reviewed_at: string | null
}

export interface MessageReview {
  conversation_id: string
  user: { id: string; username: string }
  question: string | null
  answer: {
    id: string
    content: string
    outcome: Outcome | null
    sources: SourceCard[]
    citations: SourceCard[]
    low_confidence: boolean
    guardrail: Record<string, unknown> | null
    feedback_rating: 1 | -1 | null
    feedback_comment: string | null
    trace_id: string | null
    created_at: string
  }
}

export interface EvalSet {
  id: string
  name: string
  description: string
  case_count: number
  created_at: string
}

export interface ExpectedSource {
  doc_id: string
  page: number | null
}

export interface EvalCase {
  id: string
  eval_set_id: string
  question: string
  expected_answer: string | null
  expected_sources: ExpectedSource[]
  collection_ids: string[]
  run_as_group_ids: string[]
  unanswerable: boolean
  origin: string
  source_message_id: string | null
  created_at: string
}

export interface CaseInput {
  question: string
  expected_answer: string | null
  expected_sources: ExpectedSource[]
  collection_ids: string[]
  run_as_group_ids: string[]
  unanswerable: boolean
}

export interface ImportResult {
  created: number
  errors: { row: number; message: string }[]
}

export type RunStatus = "queued" | "running" | "completed" | "failed"

export interface RunSummary {
  metrics?: Record<string, number | null>
  idk_accuracy?: number | null
  answered_rate?: number | null
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
  cost_per_question_usd?: number | null
  errors?: number
  score?: number | null
}

export interface EvalRun {
  id: string
  eval_set_id: string
  rag_config_id: string | null
  rag_config_version: number | null
  status: RunStatus
  error: string | null
  case_count: number
  summary: RunSummary
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface EvalResult {
  id: string
  case_id: string | null
  question: string
  unanswerable: boolean
  outcome: string
  answer: string
  sources: SourceCard[]
  metrics: Record<string, number | null>
  latency_ms: number
  cost_usd: number
  trace_id: string | null
  error: string | null
}

export interface EvalRunDetail extends EvalRun {
  results: EvalResult[]
}

export interface ComparedSide {
  outcome: string
  metrics: Record<string, number | null>
  answer: string
}

export interface Comparison {
  a: { id: string; summary: RunSummary }
  b: { id: string; summary: RunSummary }
  deltas: Record<string, number>
  questions: {
    case_id: string
    question: string
    a: ComparedSide
    b: ComparedSide
    regressed: boolean
    reasons: string[]
  }[]
}

export type CategoryAction = "block" | "flag" | "off"
export const MODERATION_CATEGORIES = [
  "violence",
  "hate",
  "harassment",
  "sexual",
  "illegal",
  "weapons",
  "self_harm",
] as const
export type ModerationCategory = (typeof MODERATION_CATEGORIES)[number]

export interface GuardrailSettings {
  rate_limit_per_minute: number
  max_question_chars: number
  moderation: Record<ModerationCategory, CategoryAction>
  self_harm_support: boolean
  injection_check: boolean
  exfiltration_check: boolean
  scope_check: boolean
  scope_description: string
  classifier_model: string
  blocked_message: string
  off_topic_message: string
  support_message: string
  pii_redaction: boolean
  pii_patterns: { name: string; regex: string }[]
  system_prompt_leak_check: boolean
  groundedness_check: boolean
  judge_model: string
  strike_limit: number
  strike_window_hours: number
  strike_lock_hours: number
  user_daily_cost_usd: number
  installation_daily_cost_usd: number
  cost_alert_ratio: number
}

export const RERANKER_MODELS = [
  "Xenova/ms-marco-MiniLM-L-12-v2",
  "Xenova/ms-marco-MiniLM-L-6-v2",
  "BAAI/bge-reranker-base",
  "jinaai/jina-reranker-v2-base-multilingual",
] as const

export interface RagConfig {
  chat_model: string
  rewrite_model: string
  fallback_model: string | null
  eval_judge_model: string
  reranker_model: (typeof RERANKER_MODELS)[number]
  search_top_k: number
  rerank_top_n: number
  rerank_threshold: number
  history_turns: number
  system_prompt: string
  rewrite_prompt: string
  not_found_message: string
  prices: Record<string, { input_per_mtok: number; output_per_mtok: number }>
  guardrails: GuardrailSettings
}

export interface LatestEval {
  run_id: string
  eval_set_id: string
  score: number | null
  finished_at: string | null
}

export interface RagConfigVersion {
  id: string
  version: number
  note: string
  is_active: boolean
  created_at: string
  activated_at: string | null
  latest_eval: LatestEval | null
  config: RagConfig
}

export interface ActiveConfig {
  version: number | null
  config: RagConfig
  latest_eval: LatestEval | null
}

export interface Branding {
  app_name: string
  primary_color: string | null
  logo_url: string | null
}

export interface KeyStatus {
  source: "database" | "environment" | "none" | "unreadable"
  last4: string | null
  updated_at: string | null
  secrets_key_configured: boolean
}
```

`User` stays as it is, and `AdminUser` extends it.

- [ ] **Step 3: Write the API client**

In `frontend/lib/api.ts`, add to `api` (it's public, and used on the sign-in page too):

```ts
  branding: () => apiJson<Branding>("/api/branding"),
```

(Import `Branding` from `@/lib/types`.)

`frontend/lib/admin-api.ts`:

```ts
import { apiJson } from "@/lib/api"
import type {
  ActiveConfig,
  AdminCollection,
  AdminDocument,
  AdminNotification,
  AdminUser,
  AuditEntry,
  AuditFilters,
  Branding,
  CaseInput,
  Chunk,
  CollectionInput,
  CollectionUpdate,
  Comparison,
  Dashboard,
  DocumentVersion,
  EvalCase,
  EvalRun,
  EvalRunDetail,
  EvalSet,
  Group,
  ImportResult,
  KeyStatus,
  MessageReview,
  RagConfig,
  RagConfigVersion,
  ReviewItem,
  ReviewKind,
  UploadResult,
  UserCreate,
  UserUpdate,
} from "@/lib/types"

type Params = Record<string, string | number | boolean | null | undefined>

/** Query string from the defined, non-empty params ("" when there are none). */
export function qs(params: Params): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

function upload<T>(path: string, files: File[], field: string): Promise<T> {
  const form = new FormData()
  for (const file of files) form.append(field, file)
  return apiJson<T>(path, { method: "POST", body: form })
}

const A = "/api/admin"

export const adminApi = {
  dashboard: (days: number) => apiJson<Dashboard>(`${A}/dashboard?days=${days}`),
  notifications: (unread = false) =>
    apiJson<AdminNotification[]>(`${A}/notifications${qs({ unread: unread || undefined })}`),
  markNotificationRead: (id: string) =>
    apiJson<AdminNotification>(`${A}/notifications/${id}/read`, send("POST")),

  users: () => apiJson<AdminUser[]>(`${A}/users`),
  createUser: (body: UserCreate) => apiJson<AdminUser>(`${A}/users`, send("POST", body)),
  updateUser: (id: string, body: UserUpdate) =>
    apiJson<AdminUser>(`${A}/users/${id}`, send("PATCH", body)),
  resetPassword: (id: string, new_password: string) =>
    apiJson<AdminUser>(`${A}/users/${id}/reset-password`, send("POST", { new_password })),
  groups: () => apiJson<Group[]>(`${A}/groups`),
  createGroup: (body: { name: string; description: string }) =>
    apiJson<Group>(`${A}/groups`, send("POST", body)),

  collections: () => apiJson<AdminCollection[]>(`${A}/collections`),
  createCollection: (body: CollectionInput) =>
    apiJson<AdminCollection>(`${A}/collections`, send("POST", body)),
  updateCollection: (id: string, body: CollectionUpdate) =>
    apiJson<AdminCollection>(`${A}/collections/${id}`, send("PATCH", body)),

  documents: (collectionId: string, includeDeleted: boolean) =>
    apiJson<AdminDocument[]>(
      `${A}/collections/${collectionId}/documents${qs({ include_deleted: includeDeleted || undefined })}`
    ),
  document: (id: string) => apiJson<AdminDocument>(`${A}/documents/${id}`),
  uploadDocuments: (collectionId: string, files: File[]) =>
    upload<UploadResult[]>(`${A}/collections/${collectionId}/documents`, files, "files"),
  setDocumentGroups: (id: string, group_ids: string[]) =>
    apiJson<AdminDocument>(`${A}/documents/${id}/groups`, send("PUT", { group_ids })),
  deleteDocument: (id: string, password: string) =>
    apiJson<AdminDocument>(`${A}/documents/${id}/delete`, send("POST", { password })),
  restoreDocument: (id: string) =>
    apiJson<AdminDocument>(`${A}/documents/${id}/restore`, send("POST")),
  retryVersion: (versionId: string) =>
    apiJson<DocumentVersion>(`${A}/versions/${versionId}/retry`, send("POST")),
  chunks: (documentId: string, versionId?: string) =>
    apiJson<Chunk[]>(`${A}/documents/${documentId}/chunks${qs({ version_id: versionId })}`),

  audit: (filters: AuditFilters, beforeId?: number, limit = 50) =>
    apiJson<AuditEntry[]>(`${A}/audit${qs({ ...filters, before_id: beforeId, limit })}`),
  auditExportUrl: (filters: AuditFilters) => `${A}/audit/export${qs({ ...filters })}`,

  reviewQueue: (kind: ReviewKind | undefined, includeReviewed: boolean, offset = 0) =>
    apiJson<ReviewItem[]>(
      `${A}/review-queue${qs({ kind, include_reviewed: includeReviewed || undefined, limit: 50, offset })}`
    ),
  reviewMessage: (messageId: string) =>
    apiJson<MessageReview>(`${A}/review-queue/messages/${messageId}`),
  markReviewed: (kind: ReviewKind, itemId: string) =>
    apiJson<void>(`${A}/review-queue/${kind}/${itemId}/reviewed`, send("POST")),
  addToEvalSet: (
    messageId: string,
    body: { eval_set_id: string; expected_answer: string | null; unanswerable: boolean }
  ) =>
    apiJson<EvalCase>(`${A}/review-queue/messages/${messageId}/add-to-eval-set`, send("POST", body)),

  evalSets: () => apiJson<EvalSet[]>(`${A}/eval-sets`),
  evalSet: (id: string) => apiJson<EvalSet>(`${A}/eval-sets/${id}`),
  createEvalSet: (body: { name: string; description: string }) =>
    apiJson<EvalSet>(`${A}/eval-sets`, send("POST", body)),
  deleteEvalSet: (id: string) => apiJson<void>(`${A}/eval-sets/${id}`, send("DELETE")),
  evalCases: (setId: string) => apiJson<EvalCase[]>(`${A}/eval-sets/${setId}/cases`),
  createCase: (setId: string, body: CaseInput) =>
    apiJson<EvalCase>(`${A}/eval-sets/${setId}/cases`, send("POST", body)),
  deleteCase: (caseId: string) => apiJson<void>(`${A}/eval-cases/${caseId}`, send("DELETE")),
  importCases: (setId: string, file: File) =>
    upload<ImportResult>(`${A}/eval-sets/${setId}/import`, [file], "file"),
  evalRuns: (setId?: string) => apiJson<EvalRun[]>(`${A}/eval-runs${qs({ eval_set_id: setId })}`),
  evalRun: (id: string) => apiJson<EvalRunDetail>(`${A}/eval-runs/${id}`),
  startRun: (body: { eval_set_id: string; rag_config_id: string | null }) =>
    apiJson<EvalRun>(`${A}/eval-runs`, send("POST", body)),
  compareRuns: (a: string, b: string) =>
    apiJson<Comparison>(`${A}/eval-runs/compare${qs({ a, b })}`),

  ragConfigs: () => apiJson<RagConfigVersion[]>(`${A}/rag-configs`),
  activeConfig: () => apiJson<ActiveConfig>(`${A}/rag-configs/active`),
  createConfig: (config: RagConfig, note: string) =>
    apiJson<RagConfigVersion>(`${A}/rag-configs`, send("POST", { config, note })),
  activateConfig: (id: string, password: string) =>
    apiJson<RagConfigVersion>(`${A}/rag-configs/${id}/activate`, send("POST", { password })),

  updateBranding: (body: { app_name: string; primary_color: string | null }) =>
    apiJson<Branding>(`${A}/settings/branding`, send("PUT", body)),
  uploadLogo: (file: File) => upload<Branding>(`${A}/settings/branding/logo`, [file], "file"),
  removeLogo: () => apiJson<Branding>(`${A}/settings/branding/logo`, send("DELETE")),
  openaiKey: () => apiJson<KeyStatus>(`${A}/settings/openai-key`),
  setOpenaiKey: (api_key: string, password: string) =>
    apiJson<KeyStatus>(`${A}/settings/openai-key`, send("PUT", { api_key, password })),
  clearOpenaiKey: (password: string) =>
    apiJson<KeyStatus>(`${A}/settings/openai-key/clear`, send("POST", { password })),
}
```

Prettier wraps a few of these lines; run `npm run format` on the file. `apiFetch` already skips the JSON `Content-Type` for `FormData`, so uploads send a multipart boundary.

- [ ] **Step 4: Write the failing unit tests**

`frontend/lib/format.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { formatBytes, formatPercent, formatUsd } from "@/lib/format"

describe("format", () => {
  it("formats rates, money and sizes", () => {
    expect(formatPercent(null)).toBe("—")
    expect(formatPercent(0.4567)).toBe("46%")
    expect(formatPercent(0)).toBe("0%")
    expect(formatUsd(0.75)).toBe("$0.75")
    expect(formatUsd(0.0042)).toBe("$0.0042")
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB")
  })
})
```

`frontend/lib/branding.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { contrastText } from "@/lib/branding"

describe("contrastText", () => {
  it("picks black on light colors and white on dark ones", () => {
    expect(contrastText("#ffffff")).toBe("#000000")
    expect(contrastText("#FACC15")).toBe("#000000")
    expect(contrastText("#1d4ed8")).toBe("#ffffff")
    expect(contrastText("#000000")).toBe("#ffffff")
  })
})
```

Run: `npm test -- lib/format.test.ts lib/branding.test.ts`
Expected: FAIL (the modules are missing).

- [ ] **Step 5: Write `roles`, `format` and `branding`**

`frontend/lib/roles.ts`:

```ts
import type { Role, User } from "@/lib/types"

const RANK: Record<Role, number> = { user: 0, admin: 1, super_admin: 2 }

export const isAdmin = (user: Pick<User, "role">) => RANK[user.role] >= RANK.admin
export const isSuperAdmin = (user: Pick<User, "role">) => user.role === "super_admin"
```

`frontend/lib/format.ts`:

```ts
const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
})

export const formatDateTime = (iso: string) => dateTime.format(new Date(iso))

export const formatPercent = (rate: number | null | undefined) =>
  rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`

export function formatUsd(amount: number): string {
  const digits = amount !== 0 && Math.abs(amount) < 0.01 ? 4 : 2
  return `$${amount.toFixed(digits)}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
```

`frontend/lib/branding.ts`:

```ts
"use client"

import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { APP_NAME } from "@/lib/config"

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

/** Black or white text, whichever contrasts more with `hex` (#rrggbb). */
export function contrastText(hex: string): "#000000" | "#ffffff" {
  const l = luminance(hex)
  return (l + 0.05) / 0.05 >= 1.05 / (l + 0.05) ? "#000000" : "#ffffff"
}

/** Branding from admin Settings; defaults while loading or when the API is unreachable. */
export function useBranding() {
  const { data } = useQuery({
    queryKey: ["branding"],
    queryFn: api.branding,
    staleTime: 5 * 60_000,
  })
  return {
    appName: data?.app_name ?? APP_NAME,
    primaryColor: data?.primary_color ?? null,
    logoUrl: data?.logo_url ?? null,
  }
}
```

Run: `npm test -- lib/format.test.ts lib/branding.test.ts`
Expected: PASS.

- [ ] **Step 6: Apply branding**

`frontend/components/branding.tsx`:

```tsx
"use client"

import { MessagesSquareIcon } from "lucide-react"
import { usePathname } from "next/navigation"
import { useEffect } from "react"

import { contrastText, useBranding } from "@/lib/branding"
import { cn } from "@/lib/utils"

const COLOR_VARS = ["--primary", "--sidebar-primary", "--ring"]
const TEXT_VARS = ["--primary-foreground", "--sidebar-primary-foreground"]

/** Applies the configured primary color and app name to the whole page. */
export function BrandingEffect() {
  const { appName, primaryColor } = useBranding()
  const pathname = usePathname()
  useEffect(() => {
    document.title = appName // re-applied after navigations reset the title
  }, [appName, pathname])
  useEffect(() => {
    const style = document.documentElement.style
    for (const name of [...COLOR_VARS, ...TEXT_VARS]) style.removeProperty(name)
    if (!primaryColor) return
    const text = contrastText(primaryColor)
    for (const name of COLOR_VARS) style.setProperty(name, primaryColor)
    for (const name of TEXT_VARS) style.setProperty(name, text)
  }, [primaryColor])
  return null
}

export function BrandMark({ className }: { className?: string }) {
  const { logoUrl } = useBranding()
  if (logoUrl) {
    return (
      // A small same-origin logo; next/image adds nothing here.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={logoUrl} alt="" className={cn("size-8 rounded-lg object-contain", className)} />
    )
  }
  return (
    <div
      className={cn(
        "flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground",
        className
      )}
    >
      <MessagesSquareIcon className="size-4" />
    </div>
  )
}
```

In `frontend/components/providers.tsx`, render `<BrandingEffect />` inside `QueryClientProvider`, just before `<TooltipProvider>`.

`frontend/components/auth/auth-layout.tsx`: add `"use client"` and use `const { appName } = useBranding()`. Replace the icon box with `<BrandMark className="size-6 rounded-md" />` and `{APP_NAME}` with `{appName}`. Remove the now-unused imports.

`frontend/components/app-sidebar.tsx`: replace the icon box with `<BrandMark />` and `{APP_NAME}` with `{appName}` from `useBranding()`, then remove the unused imports.

- [ ] **Step 7: Write the failing gate and sidebar tests**

`frontend/app/admin/layout.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import AdminLayout from "@/app/admin/layout"
import { jsonResponse, renderWithProviders } from "@/test/render"

const replace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/admin",
}))

const me = (role: string) => ({
  id: "u1",
  username: "ada",
  full_name: "Ada L",
  role,
  is_active: true,
  must_change_password: false,
  groups: [],
})

function mockApi(role: string) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input)
    if (url === "/api/auth/me") return jsonResponse(me(role))
    if (url.startsWith("/api/admin/notifications")) return jsonResponse([])
    return jsonResponse({ app_name: "Acme", primary_color: null, logo_url: null })
  })
}

describe("AdminLayout", () => {
  it("sends non-admins to /app without rendering the page", async () => {
    const fetchMock = mockApi("user")
    renderWithProviders(
      <AdminLayout>
        <p>secret page</p>
      </AdminLayout>
    )
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app"))
    expect(screen.queryByText("secret page")).toBeNull()
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/admin"))
    ).toBe(false)
  })

  it("renders the console for admins", async () => {
    mockApi("admin")
    renderWithProviders(
      <AdminLayout>
        <p>admin page</p>
      </AdminLayout>
    )
    expect(await screen.findByText("admin page")).toBeInTheDocument()
  })
})
```

`frontend/components/admin/admin-sidebar.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AdminSidebar } from "@/components/admin/admin-sidebar"
import { SidebarProvider } from "@/components/ui/sidebar"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("next/navigation", () => ({ usePathname: () => "/admin/users" }))
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
}))

function mockApi(role: string, unread: unknown[] = []) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input)
    if (url === "/api/auth/me")
      return jsonResponse({
        id: "u1",
        username: "ada",
        full_name: "Ada",
        role,
        is_active: true,
        must_change_password: false,
        groups: [],
      })
    if (url.startsWith("/api/admin/notifications")) return jsonResponse(unread)
    return jsonResponse({ app_name: "Acme", primary_color: null, logo_url: null })
  })
}

const renderSidebar = () =>
  renderWithProviders(
    <SidebarProvider>
      <AdminSidebar />
    </SidebarProvider>
  )

describe("AdminSidebar", () => {
  it("hides super-admin pages from admins and marks the current page", async () => {
    mockApi("admin", [{ id: "n1" }, { id: "n2" }])
    renderSidebar()
    const users = await screen.findByRole("link", { name: /Users & groups/ })
    expect(users).toHaveAttribute("data-active", "true")
    expect(screen.getByRole("link", { name: /Audit log/ })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Settings/ })).toBeNull()
    expect(screen.queryByRole("link", { name: /Guardrails/ })).toBeNull()
    expect(await screen.findByLabelText("2 unread")).toBeInTheDocument()
  })

  it("shows super-admin pages to super admins", async () => {
    mockApi("super_admin")
    renderSidebar()
    expect(await screen.findByRole("link", { name: /Settings/ })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Models & RAG config/ })).toBeInTheDocument()
  })
})
```

`frontend/components/admin/password-dialog.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { PasswordDialog } from "@/components/admin/password-dialog"
import { ApiError } from "@/lib/api"

describe("PasswordDialog", () => {
  it("keeps the dialog open on a wrong password", async () => {
    const onOpenChange = vi.fn()
    const onConfirm = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(403, "password_confirmation_failed", "Re-enter your password to confirm")
      )
      .mockResolvedValueOnce(undefined)
    render(
      <PasswordDialog
        open
        onOpenChange={onOpenChange}
        title="Delete document"
        description="This hides the document from answers."
        confirmLabel="Delete"
        destructive
        onConfirm={onConfirm}
      />
    )
    const input = screen.getByLabelText("Your password")
    await userEvent.type(input, "nope")
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Re-enter your password to confirm"
    )
    expect(onOpenChange).not.toHaveBeenCalled()

    await userEvent.clear(input)
    await userEvent.type(input, "right-password")
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(onConfirm).toHaveBeenLastCalledWith("right-password")
  })
})
```

Run: `npm test -- app/admin components/admin`
Expected: FAIL (the modules are missing).

- [ ] **Step 8: Write the gate and the layouts**

`frontend/components/me-gate.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import type { User } from "@/lib/types"

const anyone = () => true

/**
 * Renders children only for a signed-in user who passes `allow` (pass a module-level
 * function so its identity is stable). Forced password changes go to /change-password,
 * users who fail `allow` go to `redirectTo`. A 401 is handled globally (sign-out).
 */
export function MeGate({
  allow = anyone,
  redirectTo = "/app",
  children,
}: {
  allow?: (me: User) => boolean
  redirectTo?: string
  children: ReactNode
}) {
  const router = useRouter()
  const { data: me, isError, isFetching, refetch } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
  })
  useEffect(() => {
    if (!me) return
    if (me.must_change_password) router.replace("/change-password")
    else if (!allow(me)) router.replace(redirectTo)
  }, [me, allow, redirectTo, router])

  if (me && !me.must_change_password && allow(me)) return <>{children}</>
  if (me) return null
  return (
    <div className="flex h-svh flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
      {isError ? (
        <>
          <p>Can&apos;t reach the server.</p>
          <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refetch()}>
            Retry
          </Button>
        </>
      ) : (
        "Loading…"
      )}
    </div>
  )
}
```

Refactor `frontend/app/app/layout.tsx` to:

```tsx
"use client"

import type { ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { CollectionSelectionProvider } from "@/components/chat/collection-selection"
import { MeGate } from "@/components/me-gate"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <MeGate>
      <CollectionSelectionProvider>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset className="flex h-svh flex-col">
            <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
              <SidebarTrigger />
            </header>
            <div className="min-h-0 flex-1">{children}</div>
          </SidebarInset>
        </SidebarProvider>
      </CollectionSelectionProvider>
    </MeGate>
  )
}
```

`frontend/app/admin/layout.tsx`:

```tsx
"use client"

import type { ReactNode } from "react"

import { AdminSidebar } from "@/components/admin/admin-sidebar"
import { MeGate } from "@/components/me-gate"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { isAdmin } from "@/lib/roles"

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <MeGate allow={isAdmin}>
      <SidebarProvider>
        <AdminSidebar />
        <SidebarInset className="flex min-h-svh flex-col">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger />
            <span className="text-sm text-muted-foreground">Admin console</span>
          </header>
          <main className="flex-1 p-4 md:p-6">{children}</main>
        </SidebarInset>
      </SidebarProvider>
    </MeGate>
  )
}
```

In `frontend/proxy.ts`, change the matcher to `["/app/:path*", "/admin/:path*", "/change-password"]`. `:path*` matches zero or more segments, so `/admin` itself is covered (as `/app` already is).

- [ ] **Step 9: Write the sidebar and the shared admin components**

`frontend/components/admin/admin-sidebar.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import {
  BellIcon,
  CpuIcon,
  FileTextIcon,
  FlaskConicalIcon,
  FolderLockIcon,
  InboxIcon,
  LayoutDashboardIcon,
  ScrollTextIcon,
  SettingsIcon,
  ShieldIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { BrandMark } from "@/components/branding"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { UserMenu } from "@/components/user-menu"
import { adminApi } from "@/lib/admin-api"
import { api } from "@/lib/api"
import { useBranding } from "@/lib/branding"
import { isSuperAdmin } from "@/lib/roles"

interface NavItem {
  title: string
  href: string
  icon: LucideIcon
  superAdmin?: boolean
}

export const ADMIN_NAV: NavItem[] = [
  { title: "Dashboard", href: "/admin", icon: LayoutDashboardIcon },
  { title: "Documents", href: "/admin/documents", icon: FileTextIcon },
  { title: "Collections & access", href: "/admin/collections", icon: FolderLockIcon },
  { title: "Users & groups", href: "/admin/users", icon: UsersIcon },
  { title: "Evaluation", href: "/admin/evaluation", icon: FlaskConicalIcon },
  { title: "Review queue", href: "/admin/review", icon: InboxIcon },
  { title: "Audit log", href: "/admin/audit", icon: ScrollTextIcon },
  { title: "Notifications", href: "/admin/notifications", icon: BellIcon },
  { title: "Models & RAG config", href: "/admin/models", icon: CpuIcon, superAdmin: true },
  { title: "Guardrails", href: "/admin/guardrails", icon: ShieldIcon, superAdmin: true },
  { title: "Settings", href: "/admin/settings", icon: SettingsIcon, superAdmin: true },
]

const isActive = (pathname: string, href: string) =>
  href === "/admin" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`)

export function AdminSidebar() {
  const pathname = usePathname() ?? ""
  const { appName } = useBranding()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const { data: unread } = useQuery({
    queryKey: ["admin", "notifications", "unread"],
    queryFn: () => adminApi.notifications(true),
    refetchInterval: 60_000,
  })
  const items = ADMIN_NAV.filter((item) => !item.superAdmin || (me && isSuperAdmin(me)))
  return (
    <Sidebar>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/admin">
                <BrandMark />
                <span className="truncate font-medium">{appName}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Admin console</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={isActive(pathname, item.href)}>
                    <Link href={item.href}>
                      <item.icon /> {item.title}
                    </Link>
                  </SidebarMenuButton>
                  {item.href === "/admin/notifications" && unread && unread.length > 0 && (
                    <SidebarMenuBadge aria-label={`${unread.length} unread`}>
                      {unread.length}
                    </SidebarMenuBadge>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <UserMenu />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
```

`SidebarMenuButton` with `isActive` sets `data-active="true"` on the rendered element. Since `asChild` is used, that element is the `<a>`, which the test relies on.

`frontend/components/admin/page-header.tsx`:

```tsx
import type { ReactNode } from "react"

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
```

`frontend/components/admin/super-admin-only.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"

import { api } from "@/lib/api"
import { isSuperAdmin } from "@/lib/roles"

/** Renders children (and so runs their queries) only for super admins. */
export function SuperAdminOnly({ children }: { children: ReactNode }) {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  if (!me) return null
  if (!isSuperAdmin(me))
    return (
      <p className="text-sm text-muted-foreground">Only super admins can open this page.</p>
    )
  return <>{children}</>
}
```

`frontend/components/admin/password-dialog.tsx`:

```tsx
"use client"

import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ApiError } from "@/lib/api"

/** Confirmation with password re-entry for destructive actions (spec §5.3). */
export function PasswordDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  destructive = false,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel?: string
  destructive?: boolean
  onConfirm: (password: string) => Promise<unknown>
}) {
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  function close() {
    setPassword("")
    setError(null)
    onOpenChange(false)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await onConfirm(password)
      close()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.")
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="confirm-password">Your password</FieldLabel>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
            />
          </Field>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant={destructive ? "destructive" : "default"}
              disabled={pending || !password}
            >
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
```

`frontend/components/admin/group-checklist.tsx`:

```tsx
"use client"

import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import type { Group } from "@/lib/types"

/** Multi-select checkboxes over `{id, name}` items (groups, or collections); `value` holds ids. */
export function GroupChecklist({
  groups,
  value,
  onChange,
  idPrefix,
  empty = "No groups yet. Create one first.",
}: {
  groups: Group[]
  value: string[]
  onChange: (ids: string[]) => void
  idPrefix: string
  empty?: string
}) {
  if (groups.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <div className="grid max-h-48 gap-2 overflow-y-auto">
      {groups.map((group) => {
        const id = `${idPrefix}-${group.id}`
        const checked = value.includes(group.id)
        return (
          <div key={group.id} className="flex items-center gap-2">
            <Checkbox
              id={id}
              checked={checked}
              onCheckedChange={(next) =>
                onChange(
                  next === true ? [...value, group.id] : value.filter((g) => g !== group.id)
                )
              }
            />
            <Label htmlFor={id}>{group.name}</Label>
          </div>
        )
      })}
    </div>
  )
}
```

`frontend/components/admin/data-table.tsx`:

```tsx
"use client"

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table"
import { ArrowUpDownIcon } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/** The dashboard-01 data-table pattern: TanStack Table rendered with shadcn `table`. */
export function DataTable<T>({
  columns,
  data,
  isLoading = false,
  empty = "Nothing here yet.",
  getRowId,
}: {
  columns: ColumnDef<T>[]
  data: T[]
  isLoading?: boolean
  empty?: string
  getRowId?: (row: T) => string
}) {
  const [sorting, setSorting] = useState<SortingState>([])
  // TanStack Table returns new functions each render; this component isn't memoized.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  })
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader className="bg-muted">
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : header.column.getCanSort() &&
                    header.column.columnDef.enableSorting ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="-ml-2"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      <ArrowUpDownIcon />
                    </Button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {isLoading ? (
            Array.from({ length: 3 }, (_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={columns.length}>
                  <Skeleton className="h-5 w-full" />
                </TableCell>
              </TableRow>
            ))
          ) : table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="h-20 text-center text-muted-foreground"
              >
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
```

A column is sortable only when its definition sets `enableSorting: true`. If lint reports the `eslint-disable` line as unused (because the rule isn't active), remove the comment.

- [ ] **Step 10: Add the user menu links**

In `frontend/components/user-menu.tsx`:
- add `const pathname = usePathname() ?? ""` (import from `next/navigation`);
- import `isAdmin` and the `MessagesSquareIcon` and `ShieldIcon` icons;
- after the Profile item, add:

```tsx
            {me && isAdmin(me) && (
              <DropdownMenuItem asChild>
                {pathname.startsWith("/admin") ? (
                  <Link href="/app">
                    <MessagesSquareIcon /> Chat
                  </Link>
                ) : (
                  <Link href="/admin">
                    <ShieldIcon /> Admin console
                  </Link>
                )}
              </DropdownMenuItem>
            )}
```

- [ ] **Step 11: Run all frontend checks**

Run: `npm test && npm run lint && npm run typecheck && npm run build`
Expected: all green, including the Plan 6 tests (`app/app/layout.test.tsx` still finds "Can't reach the server." and Retry).

- [ ] **Step 12: Commit**

```bash
git add frontend/components/ui frontend/package.json frontend/package-lock.json frontend/lib frontend/components/me-gate.tsx frontend/components/branding.tsx frontend/components/admin frontend/app/admin/layout.tsx frontend/app/admin/layout.test.tsx frontend/app/app/layout.tsx frontend/proxy.ts frontend/components/providers.tsx frontend/components/user-menu.tsx frontend/components/app-sidebar.tsx frontend/components/auth/auth-layout.tsx
git commit -m "feat(admin): console shell with role gate, sidebar, branding and shared components"
```

---

### Task 5: Dashboard and notifications pages

**Files:**
- Create: `frontend/app/admin/page.tsx`, `frontend/components/admin/questions-chart.tsx`, `frontend/app/admin/notifications/page.tsx`
- Test: `frontend/app/admin/page.test.tsx`, `frontend/app/admin/notifications/page.test.tsx`

**Interfaces:**
- Consumes: `adminApi.dashboard`, `adminApi.notifications`, `adminApi.markNotificationRead`, `PageHeader`, `formatPercent`, `formatUsd`, `formatDateTime`, and the types `Dashboard`, `DailyPoint`, `AdminNotification`.
- Produces: the `/admin` and `/admin/notifications` pages.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/page.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import DashboardPage from "@/app/admin/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("@/components/admin/questions-chart", () => ({
  QuestionsChart: () => <div data-testid="chart" />,
}))

const dashboard = {
  days: 30,
  totals: {
    questions: 1234,
    active_users: 56,
    input_tokens: 1000,
    output_tokens: 500,
    cost_usd: 12.5,
    thumbs_up_rate: 0.8,
    not_found_rate: null,
    low_confidence_rate: 0.05,
    guardrail_blocks: 3,
  },
  daily: [],
  ingestion: { queued: 2, parsing: 1, ready: 40, failed: 1, rejected: 0 },
  health: { database: "ok", qdrant: "error", redis: "ok" },
}

describe("DashboardPage", () => {
  it("shows the figures, ingestion and health", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => jsonResponse(dashboard))
    renderWithProviders(<DashboardPage />)
    expect(await screen.findByText("1,234")).toBeInTheDocument()
    expect(screen.getByText("80%")).toBeInTheDocument()
    expect(screen.getByText("$12.50")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument() // no "I don't know" rate yet
    expect(screen.getByText("3 in progress")).toBeInTheDocument()
    expect(screen.getByText("1 failed")).toBeInTheDocument()
    expect(screen.getByText("Qdrant: error")).toBeInTheDocument()
  })
})
```

`frontend/app/admin/notifications/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import NotificationsPage from "@/app/admin/notifications/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const note = {
  id: "n1",
  kind: "strike_lock",
  title: "User bob was locked",
  body: "3 strikes in 24 hours",
  target_type: "user",
  target_id: "u2",
  created_at: "2026-10-08T10:00:00Z",
  read_at: null,
}

describe("NotificationsPage", () => {
  it("marks a notification as read", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) =>
        init?.method === "POST"
          ? jsonResponse({ ...note, read_at: "2026-10-08T11:00:00Z" })
          : jsonResponse([note])
      )
    renderWithProviders(<NotificationsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Mark as read" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) => String(u) === "/api/admin/notifications/n1/read" && i?.method === "POST"
        )
      ).toBe(true)
    )
  })
})
```

Run: `npm test -- app/admin/page.test.tsx app/admin/notifications`
Expected: FAIL.

- [ ] **Step 2: Write the chart**

`frontend/components/admin/questions-chart.tsx`:

```tsx
"use client"

import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import type { DailyPoint } from "@/lib/types"

const config = {
  questions: { label: "Questions", color: "var(--chart-1)" },
  not_found: { label: "I don't know", color: "var(--chart-2)" },
} satisfies ChartConfig

export function QuestionsChart({ data }: { data: DailyPoint[] }) {
  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <AreaChart data={data} margin={{ left: 12, right: 12 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
          tickFormatter={(value: string) => value.slice(5)}
        />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        {(["questions", "not_found"] as const).map((key) => (
          <Area
            key={key}
            dataKey={key}
            type="monotone"
            fill={`var(--color-${key})`}
            fillOpacity={0.3}
            stroke={`var(--color-${key})`}
          />
        ))}
      </AreaChart>
    </ChartContainer>
  )
}
```

- [ ] **Step 3: Write the dashboard page**

`frontend/app/admin/page.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { PageHeader } from "@/components/admin/page-header"
import { QuestionsChart } from "@/components/admin/questions-chart"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { adminApi } from "@/lib/admin-api"
import { formatPercent, formatUsd } from "@/lib/format"

const IN_PROGRESS = ["queued", "scanning", "parsing", "enriching", "chunking", "embedding", "indexing"]
const SERVICES: Record<string, string> = { database: "Database", qdrant: "Qdrant", redis: "Redis" }

export default function DashboardPage() {
  const [days, setDays] = useState(30)
  const { data, isError } = useQuery({
    queryKey: ["admin", "dashboard", days],
    queryFn: () => adminApi.dashboard(days),
    refetchInterval: 60_000,
  })

  const t = data?.totals
  const cards: [string, string][] = t
    ? [
        ["Questions", t.questions.toLocaleString("en-US")],
        ["Active users", t.active_users.toLocaleString("en-US")],
        ["Cost", formatUsd(t.cost_usd)],
        ["Tokens", (t.input_tokens + t.output_tokens).toLocaleString("en-US")],
        ["👍 rate", formatPercent(t.thumbs_up_rate)],
        ["“I don’t know” rate", formatPercent(t.not_found_rate)],
        ["Low-confidence rate", formatPercent(t.low_confidence_rate)],
        ["Guardrail blocks", t.guardrail_blocks.toLocaleString("en-US")],
      ]
    : []
  const inProgress = data
    ? IN_PROGRESS.reduce((sum, status) => sum + (data.ingestion[status] ?? 0), 0)
    : 0

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Usage and answer quality across the installation."
        actions={
          <NativeSelect
            aria-label="Period"
            value={String(days)}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <NativeSelectOption value="7">Last 7 days</NativeSelectOption>
            <NativeSelectOption value="30">Last 30 days</NativeSelectOption>
            <NativeSelectOption value="90">Last 90 days</NativeSelectOption>
          </NativeSelect>
        }
      />
      {isError && <p className="text-sm text-destructive">Could not load the dashboard.</p>}
      {data && (
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map(([label, value]) => (
              <Card key={label}>
                <CardHeader>
                  <CardDescription>{label}</CardDescription>
                  <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
                </CardHeader>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Questions per day</CardTitle>
              <CardDescription>With answers the documents didn&apos;t cover.</CardDescription>
            </CardHeader>
            <CardContent>
              <QuestionsChart data={data.daily} />
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Ingestion</CardTitle>
                <CardDescription>Document versions by status.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Badge variant="secondary">{inProgress} in progress</Badge>
                <Badge variant="secondary">{data.ingestion.ready ?? 0} ready</Badge>
                <Badge variant={data.ingestion.failed ? "destructive" : "secondary"}>
                  {data.ingestion.failed ?? 0} failed
                </Badge>
                <Badge variant="secondary">{data.ingestion.rejected ?? 0} rejected</Badge>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Service health</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {Object.entries(data.health).map(([service, state]) => (
                  <Badge key={service} variant={state === "ok" ? "secondary" : "destructive"}>
                    {SERVICES[service] ?? service}: {state}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 4: Write the notifications page**

`frontend/app/admin/notifications/page.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"

export default function NotificationsPage() {
  const queryClient = useQueryClient()
  const [unreadOnly, setUnreadOnly] = useState(true)
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "notifications", unreadOnly ? "unread" : "all"],
    queryFn: () => adminApi.notifications(unreadOnly),
  })
  const markRead = useMutation({
    mutationFn: adminApi.markNotificationRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] }),
  })

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Ingestion failures, cost caps, eval drops and strike locks."
        actions={
          <div className="flex items-center gap-2">
            <Switch id="unread-only" checked={unreadOnly} onCheckedChange={setUnreadOnly} />
            <Label htmlFor="unread-only">Unread only</Label>
          </div>
        }
      />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {data?.length === 0 && (
        <p className="text-sm text-muted-foreground">You&apos;re all caught up.</p>
      )}
      <div className="grid gap-3">
        {data?.map((note) => (
          <Card key={note.id} className={note.read_at ? "opacity-70" : undefined}>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="grid gap-1">
                <CardTitle className="text-base">{note.title}</CardTitle>
                <CardDescription>
                  {formatDateTime(note.created_at)} · {note.body}
                </CardDescription>
              </div>
              {!note.read_at && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={markRead.isPending}
                  onClick={() => markRead.mutate(note.id)}
                >
                  Mark as read
                </Button>
              )}
            </CardHeader>
          </Card>
        ))}
      </div>
    </>
  )
}
```

- [ ] **Step 5: Run the tests and checks**

Run: `npm test -- app/admin && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/admin/page.tsx frontend/app/admin/page.test.tsx frontend/components/admin/questions-chart.tsx frontend/app/admin/notifications
git commit -m "feat(admin): dashboard with figures, chart, ingestion and health; notifications page"
```

---
### Task 6: Collections & access, Users & groups

**Files:**
- Create: `frontend/app/admin/collections/page.tsx`, `frontend/components/admin/collection-dialog.tsx`
- Create: `frontend/app/admin/users/page.tsx`, `frontend/components/admin/user-dialogs.tsx`
- Test: `frontend/app/admin/collections/page.test.tsx`, `frontend/app/admin/users/page.test.tsx`

**Interfaces:**
- Consumes:
  - `adminApi`: `collections`, `createCollection`, `updateCollection`, `groups`, `createGroup`, `users`, `createUser`, `updateUser`, `resetPassword`;
  - `DataTable`, `PasswordDialog`, `PageHeader`, `GroupChecklist`;
  - `isSuperAdmin`, `formatDateTime`;
  - the types `AdminCollection`, `AdminUser`, `Group` and `Role`.
- Produces:
  - the `/admin/collections` and `/admin/users` pages;
  - `userStatuses(user, now) -> string[]` (exported from `user-dialogs.tsx`), used by the users table.
- Query keys: `["admin","collections"]`, `["admin","groups"]`, `["admin","users"]`.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/collections/page.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import CollectionsPage from "@/app/admin/collections/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const g1 = { id: "g1", name: "hr", description: "" }
const g2 = { id: "g2", name: "finance", description: "" }
const collection = {
  id: "c1",
  name: "Policies",
  description: "HR policies",
  sensitive: false,
  groups: [g1],
  created_at: "2026-10-01T00:00:00Z",
}

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (init?.method === "PATCH") return jsonResponse(collection)
    if (url === "/api/admin/groups") return jsonResponse([g1, g2])
    return jsonResponse([collection])
  })
}

const patches = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.mock.calls
    .filter(([, i]) => i?.method === "PATCH")
    .map(([, i]) => JSON.parse(String(i?.body)))

describe("CollectionsPage", () => {
  it("asks for a password only when groups change", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<CollectionsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Edit Policies" }))
    let dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByLabelText("Sensitive"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }))
    await waitFor(() => expect(patches(fetchMock)).toHaveLength(1))
    expect(patches(fetchMock)[0]).toEqual({
      name: "Policies",
      description: "HR policies",
      sensitive: true,
    })

    await userEvent.click(screen.getByRole("button", { name: "Edit Policies" }))
    dialog = await screen.findByRole("dialog")
    await userEvent.click(within(dialog).getByLabelText("finance"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }))
    await userEvent.type(await screen.findByLabelText("Your password"), "pw-123")
    await userEvent.click(screen.getByRole("button", { name: "Change access" }))
    await waitFor(() => expect(patches(fetchMock)).toHaveLength(2))
    expect(patches(fetchMock)[1]).toMatchObject({
      group_ids: ["g1", "g2"],
      password: "pw-123",
    })
  })
})
```

`frontend/app/admin/users/page.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import UsersPage from "@/app/admin/users/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const hr = { id: "g1", name: "hr", description: "" }
const bob = {
  id: "u2",
  username: "bob",
  full_name: "Bob B",
  role: "user",
  is_active: true,
  must_change_password: false,
  locked_until: null,
  chat_locked_until: "2999-01-01T00:00:00Z",
  groups: [hr],
  created_at: "2026-10-01T00:00:00Z",
}

function mockApi(myRole: string) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (url === "/api/auth/me")
      return jsonResponse({ ...bob, id: "u1", username: "me", role: myRole })
    if (init?.method === "POST" || init?.method === "PATCH") return jsonResponse(bob)
    if (url === "/api/admin/groups") return jsonResponse([hr])
    return jsonResponse([bob])
  })
}

const bodyOf = (fetchMock: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = fetchMock.mock.calls.find(([u, i]) => String(u) === url && i?.method === method)
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("UsersPage", () => {
  it("shows a chat lock and unlocks the user", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<UsersPage />)
    expect(await screen.findByText("Chat locked")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Actions for bob" }))
    await userEvent.click(await screen.findByRole("menuitem", { name: "Unlock" }))
    await waitFor(() =>
      expect(bodyOf(fetchMock, "PATCH", "/api/admin/users/u2")).toEqual({ unlock: true })
    )
  })

  it("creates a user; only super admins can grant super_admin", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<UsersPage />)
    await userEvent.click(await screen.findByRole("button", { name: "New user" }))
    const dialog = await screen.findByRole("dialog")
    const role = within(dialog).getByLabelText("Role")
    expect(within(role).queryByRole("option", { name: "Super admin" })).toBeNull()
    await userEvent.type(within(dialog).getByLabelText("Username"), "carol")
    await userEvent.type(within(dialog).getByLabelText("Full name"), "Carol C")
    await userEvent.type(within(dialog).getByLabelText("Initial password"), "start-pass-123")
    await userEvent.selectOptions(role, "admin")
    await userEvent.click(within(dialog).getByLabelText("hr"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }))
    await waitFor(() =>
      expect(bodyOf(fetchMock, "POST", "/api/admin/users")).toEqual({
        username: "carol",
        full_name: "Carol C",
        password: "start-pass-123",
        role: "admin",
        group_ids: ["g1"],
      })
    )
  })
})
```

Run: `npm test -- app/admin/collections app/admin/users`
Expected: FAIL (the modules are missing).

- [ ] **Step 2: Write the collection dialog**

`frontend/components/admin/collection-dialog.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { AdminCollection, CollectionUpdate, Group } from "@/lib/types"

const schema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
  sensitive: z.boolean(),
  group_ids: z.array(z.string()),
})
type Values = z.infer<typeof schema>

const sameIds = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().every((id, i) => id === [...b].sort()[i])

export function CollectionDialog({
  open,
  onOpenChange,
  collection,
  groups,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  collection?: AdminCollection
  groups: Group[]
}) {
  const queryClient = useQueryClient()
  const [formError, setFormError] = useState<string | null>(null)
  const [pending, setPending] = useState<CollectionUpdate | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { register, handleSubmit, control, reset, formState } = form

  useEffect(() => {
    if (!open) return
    setFormError(null)
    reset({
      name: collection?.name ?? "",
      description: collection?.description ?? "",
      sensitive: collection?.sensitive ?? false,
      group_ids: collection?.groups.map((g) => g.id) ?? [],
    })
  }, [open, collection, reset])

  const save = useMutation({
    mutationFn: (values: CollectionUpdate) =>
      collection
        ? adminApi.updateCollection(collection.id, values)
        : adminApi.createCollection({
            name: values.name ?? "",
            description: values.description ?? "",
            sensitive: values.sensitive ?? false,
            group_ids: values.group_ids ?? [],
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "collections"] })
      toast.success(collection ? "Collection updated" : "Collection created")
      onOpenChange(false)
    },
  })

  async function onSubmit(values: Values) {
    setFormError(null)
    const base = {
      name: values.name,
      description: values.description,
      sensitive: values.sensitive,
    }
    if (!collection) {
      return save.mutateAsync({ ...base, group_ids: values.group_ids }).catch(showError)
    }
    const current = collection.groups.map((g) => g.id)
    if (!sameIds(current, values.group_ids)) {
      setPending({ ...base, group_ids: values.group_ids }) // access change: password first
      return
    }
    return save.mutateAsync(base).catch(showError)
  }

  function showError(error: unknown) {
    setFormError(error instanceof ApiError ? error.message : "Could not save. Try again.")
  }

  return (
    <>
      <Dialog open={open && !pending} onOpenChange={onOpenChange}>
        <DialogContent>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>{collection ? "Edit collection" : "New collection"}</DialogTitle>
            </DialogHeader>
            <Field data-invalid={!!formState.errors.name}>
              <FieldLabel htmlFor="collection-name">Name</FieldLabel>
              <Input id="collection-name" {...register("name")} />
              <FieldError errors={[formState.errors.name]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="collection-description">Description</FieldLabel>
              <Textarea id="collection-description" rows={2} {...register("description")} />
            </Field>
            <Controller
              control={control}
              name="sensitive"
              render={({ field }) => (
                <div className="flex items-center gap-2">
                  <Switch
                    id="collection-sensitive"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                  <Label htmlFor="collection-sensitive">Sensitive</Label>
                </div>
              )}
            />
            <Field>
              <FieldLabel>Groups with access</FieldLabel>
              <FieldDescription>
                Members of these groups can ask about this collection&apos;s documents.
              </FieldDescription>
              <Controller
                control={control}
                name="group_ids"
                render={({ field }) => (
                  <GroupChecklist
                    groups={groups}
                    value={field.value ?? []}
                    onChange={field.onChange}
                    idPrefix="collection-group"
                  />
                )}
              />
            </Field>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={save.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <PasswordDialog
        open={!!pending}
        onOpenChange={(next) => {
          if (!next) setPending(null)
        }}
        title="Change who can access this collection"
        description="Answers will immediately include or exclude these documents for the affected users."
        confirmLabel="Change access"
        onConfirm={(password) => save.mutateAsync({ ...pending, password })}
      />
    </>
  )
}
```

After a successful access change, `save.onSuccess` closes the edit dialog, and `PasswordDialog` closes itself, which sets `pending` to null.

- [ ] **Step 3: Write the collections page**

`frontend/app/admin/collections/page.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useState } from "react"

import { CollectionDialog } from "@/components/admin/collection-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"
import type { AdminCollection } from "@/lib/types"

export default function CollectionsPage() {
  const collections = useQuery({ queryKey: ["admin", "collections"], queryFn: adminApi.collections })
  const groups = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.groups })
  const [editing, setEditing] = useState<AdminCollection | undefined>()
  const [open, setOpen] = useState(false)

  const columns: ColumnDef<AdminCollection>[] = [
    {
      accessorKey: "name",
      header: "Name",
      enableSorting: true,
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.name}</div>
          <div className="text-xs text-muted-foreground">{row.original.description}</div>
        </div>
      ),
    },
    {
      id: "groups",
      header: "Groups",
      cell: ({ row }) =>
        row.original.groups.length ? (
          <div className="flex flex-wrap gap-1">
            {row.original.groups.map((g) => (
              <Badge key={g.id} variant="secondary">
                {g.name}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground">No access yet</span>
        ),
    },
    {
      id: "sensitive",
      header: "Sensitive",
      cell: ({ row }) => (row.original.sensitive ? <Badge>Sensitive</Badge> : null),
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => formatDateTime(row.original.created_at),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          size="sm"
          variant="outline"
          aria-label={`Edit ${row.original.name}`}
          onClick={() => {
            setEditing(row.original)
            setOpen(true)
          }}
        >
          Edit
        </Button>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Collections & access"
        description="Collections group documents; groups decide who can ask about them."
        actions={
          <Button
            onClick={() => {
              setEditing(undefined)
              setOpen(true)
            }}
          >
            New collection
          </Button>
        }
      />
      <DataTable
        columns={columns}
        data={collections.data ?? []}
        isLoading={collections.isLoading}
        getRowId={(c) => c.id}
        empty="No collections yet."
      />
      <CollectionDialog
        open={open}
        onOpenChange={setOpen}
        collection={editing}
        groups={groups.data ?? []}
      />
    </>
  )
}
```

- [ ] **Step 4: Write the user dialogs**

`frontend/components/admin/user-dialogs.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState, type ReactNode } from "react"
import { Controller, useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { AdminUser, Group, Role } from "@/lib/types"

export const ROLE_LABELS: Record<Role, string> = {
  user: "User",
  admin: "Admin",
  super_admin: "Super admin",
}

/** Every status that applies, most important first; "Active" when nothing else does. */
export function userStatuses(user: AdminUser, now = new Date()): string[] {
  const statuses: string[] = []
  if (!user.is_active) statuses.push("Suspended")
  if (user.locked_until && new Date(user.locked_until) > now) statuses.push("Sign-in locked")
  if (user.chat_locked_until && new Date(user.chat_locked_until) > now)
    statuses.push("Chat locked")
  if (user.must_change_password) statuses.push("Must change password")
  return statuses.length ? statuses : ["Active"]
}

const errorText = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Try again."

function useUsersMutation<T>(fn: (values: T) => Promise<unknown>, done: () => void, ok: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] })
      void queryClient.invalidateQueries({ queryKey: ["admin", "groups"] })
      toast.success(ok)
      done()
    },
  })
}

function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  error,
  submitLabel,
  pending,
  onSubmit,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  error: string | null
  submitLabel: string
  pending: boolean
  onSubmit: () => void
  children: ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>
          {children}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RoleSelect({
  id,
  canGrantSuperAdmin,
  ...props
}: { id: string; canGrantSuperAdmin: boolean } & React.ComponentProps<typeof NativeSelect>) {
  const roles: Role[] = canGrantSuperAdmin ? ["user", "admin", "super_admin"] : ["user", "admin"]
  return (
    <NativeSelect id={id} {...props}>
      {roles.map((role) => (
        <NativeSelectOption key={role} value={role}>
          {ROLE_LABELS[role]}
        </NativeSelectOption>
      ))}
    </NativeSelect>
  )
}

const createSchema = z.object({
  username: z.string().trim().min(3, "At least 3 characters").max(64),
  full_name: z.string().trim().min(1, "Enter a name").max(200),
  password: z.string().min(1, "Enter an initial password").max(128),
  role: z.enum(["user", "admin", "super_admin"]),
  group_ids: z.array(z.string()),
})

export function CreateUserDialog({
  open,
  onOpenChange,
  groups,
  canGrantSuperAdmin,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  groups: Group[]
  canGrantSuperAdmin: boolean
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof createSchema>>({ resolver: zodResolver(createSchema) })
  const { register, control, reset, handleSubmit, formState } = form
  useEffect(() => {
    if (open) {
      setError(null)
      reset({ username: "", full_name: "", password: "", role: "user", group_ids: [] })
    }
  }, [open, reset])
  const create = useUsersMutation(adminApi.createUser, () => onOpenChange(false), "User created")
  const submit = handleSubmit((values) =>
    create.mutateAsync(values).catch((e) => setError(errorText(e)))
  )
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="New user"
      description="They must change this password when they first sign in."
      error={error}
      submitLabel="Create user"
      pending={create.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!formState.errors.username}>
        <FieldLabel htmlFor="new-username">Username</FieldLabel>
        <Input id="new-username" autoComplete="off" {...register("username")} />
        <FieldError errors={[formState.errors.username]} />
      </Field>
      <Field data-invalid={!!formState.errors.full_name}>
        <FieldLabel htmlFor="new-full-name">Full name</FieldLabel>
        <Input id="new-full-name" {...register("full_name")} />
        <FieldError errors={[formState.errors.full_name]} />
      </Field>
      <Field data-invalid={!!formState.errors.password}>
        <FieldLabel htmlFor="new-password">Initial password</FieldLabel>
        <Input id="new-password" type="password" autoComplete="new-password" {...register("password")} />
        <FieldError errors={[formState.errors.password]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="new-role">Role</FieldLabel>
        <RoleSelect id="new-role" canGrantSuperAdmin={canGrantSuperAdmin} {...register("role")} />
      </Field>
      <Field>
        <FieldLabel>Groups</FieldLabel>
        <Controller
          control={control}
          name="group_ids"
          render={({ field }) => (
            <GroupChecklist
              groups={groups}
              value={field.value ?? []}
              onChange={field.onChange}
              idPrefix="new-user-group"
            />
          )}
        />
      </Field>
    </FormDialog>
  )
}

const editSchema = z.object({
  full_name: z.string().trim().min(1, "Enter a name").max(200),
  role: z.enum(["user", "admin", "super_admin"]),
  group_ids: z.array(z.string()),
})

export function EditUserDialog({
  user,
  onOpenChange,
  groups,
  canGrantSuperAdmin,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
  groups: Group[]
  canGrantSuperAdmin: boolean
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof editSchema>>({ resolver: zodResolver(editSchema) })
  const { register, control, reset, handleSubmit, formState } = form
  useEffect(() => {
    if (user) {
      setError(null)
      reset({
        full_name: user.full_name,
        role: user.role,
        group_ids: user.groups.map((g) => g.id),
      })
    }
  }, [user, reset])
  const update = useUsersMutation(
    (values: z.infer<typeof editSchema>) => adminApi.updateUser(user!.id, values),
    () => onOpenChange(false),
    "User updated"
  )
  const submit = handleSubmit((values) =>
    update.mutateAsync(values).catch((e) => setError(errorText(e)))
  )
  return (
    <FormDialog
      open={!!user}
      onOpenChange={onOpenChange}
      title={`Edit ${user?.username ?? ""}`}
      error={error}
      submitLabel="Save"
      pending={update.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!formState.errors.full_name}>
        <FieldLabel htmlFor="edit-full-name">Full name</FieldLabel>
        <Input id="edit-full-name" {...register("full_name")} />
        <FieldError errors={[formState.errors.full_name]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="edit-role">Role</FieldLabel>
        <RoleSelect
          id="edit-role"
          canGrantSuperAdmin={canGrantSuperAdmin || user?.role === "super_admin"}
          {...register("role")}
        />
      </Field>
      <Field>
        <FieldLabel>Groups</FieldLabel>
        <Controller
          control={control}
          name="group_ids"
          render={({ field }) => (
            <GroupChecklist
              groups={groups}
              value={field.value ?? []}
              onChange={field.onChange}
              idPrefix="edit-user-group"
            />
          )}
        />
      </Field>
    </FormDialog>
  )
}

const resetSchema = z.object({ new_password: z.string().min(1, "Enter a password").max(128) })

export function ResetPasswordDialog({
  user,
  onOpenChange,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema) })
  useEffect(() => {
    if (user) {
      setError(null)
      form.reset({ new_password: "" })
    }
  }, [user, form])
  const reset = useUsersMutation(
    (values: z.infer<typeof resetSchema>) => adminApi.resetPassword(user!.id, values.new_password),
    () => onOpenChange(false),
    "Password reset; they must change it at next sign-in"
  )
  const submit = form.handleSubmit((values) =>
    reset.mutateAsync(values).catch((e) => setError(errorText(e)))
  )
  return (
    <FormDialog
      open={!!user}
      onOpenChange={onOpenChange}
      title={`Reset password for ${user?.username ?? ""}`}
      description="This signs them out everywhere."
      error={error}
      submitLabel="Reset password"
      pending={reset.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!form.formState.errors.new_password}>
        <FieldLabel htmlFor="reset-password">New password</FieldLabel>
        <Input
          id="reset-password"
          type="password"
          autoComplete="new-password"
          {...form.register("new_password")}
        />
        <FieldError errors={[form.formState.errors.new_password]} />
      </Field>
    </FormDialog>
  )
}

const groupSchema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
})

export function CreateGroupDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof groupSchema>>({ resolver: zodResolver(groupSchema) })
  useEffect(() => {
    if (open) {
      setError(null)
      form.reset({ name: "", description: "" })
    }
  }, [open, form])
  const create = useUsersMutation(adminApi.createGroup, () => onOpenChange(false), "Group created")
  const submit = form.handleSubmit((values) =>
    create.mutateAsync(values).catch((e) => setError(errorText(e)))
  )
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="New group"
      error={error}
      submitLabel="Create group"
      pending={create.isPending}
      onSubmit={() => void submit()}
    >
      <Field data-invalid={!!form.formState.errors.name}>
        <FieldLabel htmlFor="group-name">Name</FieldLabel>
        <Input id="group-name" {...form.register("name")} />
        <FieldError errors={[form.formState.errors.name]} />
      </Field>
      <Field>
        <FieldLabel htmlFor="group-description">Description</FieldLabel>
        <Input id="group-description" {...form.register("description")} />
      </Field>
    </FormDialog>
  )
}
```

`NativeSelect` forwards `ref` and props to a native `<select>`, so `register("role")` works. If the generated component doesn't forward `ref`, use a `Controller` with `value`/`onChange` instead.

- [ ] **Step 5: Write the users page**

`frontend/app/admin/users/page.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { MoreHorizontalIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import {
  CreateGroupDialog,
  CreateUserDialog,
  EditUserDialog,
  ResetPasswordDialog,
  ROLE_LABELS,
  userStatuses,
} from "@/components/admin/user-dialogs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { isSuperAdmin } from "@/lib/roles"
import type { AdminUser, Group, UserUpdate } from "@/lib/types"

export default function UsersPage() {
  const queryClient = useQueryClient()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users })
  const groups = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.groups })
  const [creating, setCreating] = useState(false)
  const [creatingGroup, setCreatingGroup] = useState(false)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [resetting, setResetting] = useState<AdminUser | null>(null)
  const canGrantSuperAdmin = !!me && isSuperAdmin(me)

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserUpdate }) => adminApi.updateUser(id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Could not update the user"),
  })

  const userColumns: ColumnDef<AdminUser>[] = [
    {
      accessorKey: "username",
      header: "User",
      enableSorting: true,
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.username}</div>
          <div className="text-xs text-muted-foreground">{row.original.full_name}</div>
        </div>
      ),
    },
    { accessorKey: "role", header: "Role", cell: ({ row }) => ROLE_LABELS[row.original.role] },
    {
      id: "groups",
      header: "Groups",
      cell: ({ row }) => row.original.groups.map((g) => g.name).join(", ") || "—",
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {userStatuses(row.original).map((status) => (
            <Badge key={status} variant={status === "Active" ? "secondary" : "destructive"}>
              {status}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const user = row.original
        const statuses = userStatuses(user)
        const locked = statuses.includes("Sign-in locked") || statuses.includes("Chat locked")
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" variant="ghost" aria-label={`Actions for ${user.username}`}>
                <MoreHorizontalIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setEditing(user)}>Edit</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setResetting(user)}>Reset password</DropdownMenuItem>
              {locked && (
                <DropdownMenuItem
                  onSelect={() => update.mutate({ id: user.id, body: { unlock: true } })}
                >
                  Unlock
                </DropdownMenuItem>
              )}
              {user.id !== me?.id && (
                <DropdownMenuItem
                  onSelect={() =>
                    update.mutate({ id: user.id, body: { is_active: !user.is_active } })
                  }
                >
                  {user.is_active ? "Suspend" : "Reactivate"}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )
      },
    },
  ]

  const groupColumns: ColumnDef<Group>[] = [
    { accessorKey: "name", header: "Name", enableSorting: true },
    { accessorKey: "description", header: "Description" },
  ]

  return (
    <>
      <PageHeader
        title="Users & groups"
        description="Accounts, roles and the groups that grant access to collections."
      />
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="groups">Groups</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setCreating(true)}>New user</Button>
          </div>
          <DataTable
            columns={userColumns}
            data={users.data ?? []}
            isLoading={users.isLoading}
            getRowId={(u) => u.id}
          />
        </TabsContent>
        <TabsContent value="groups" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setCreatingGroup(true)}>New group</Button>
          </div>
          <DataTable
            columns={groupColumns}
            data={groups.data ?? []}
            isLoading={groups.isLoading}
            getRowId={(g) => g.id}
            empty="No groups yet."
          />
        </TabsContent>
      </Tabs>
      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        groups={groups.data ?? []}
        canGrantSuperAdmin={canGrantSuperAdmin}
      />
      <EditUserDialog
        user={editing}
        onOpenChange={(open) => !open && setEditing(null)}
        groups={groups.data ?? []}
        canGrantSuperAdmin={canGrantSuperAdmin}
      />
      <ResetPasswordDialog user={resetting} onOpenChange={(open) => !open && setResetting(null)} />
      <CreateGroupDialog open={creatingGroup} onOpenChange={setCreatingGroup} />
    </>
  )
}
```

- [ ] **Step 6: Run the tests and checks**

Run: `npm test -- app/admin && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/admin/collections frontend/app/admin/users frontend/components/admin/collection-dialog.tsx frontend/components/admin/user-dialogs.tsx
git commit -m "feat(admin): collections & access and users & groups pages"
```

---

### Task 7: Documents — upload, live status, versions, retry, delete/restore, access, chunk inspector

**Files:**
- Create: `frontend/app/admin/documents/page.tsx`, `frontend/components/admin/document-sheet.tsx`
- Test: `frontend/app/admin/documents/page.test.tsx`

**Interfaces:**
- Consumes:
  - `adminApi`: `collections`, `documents`, `document`, `uploadDocuments`, `retryVersion`, `deleteDocument`, `restoreDocument`, `setDocumentGroups`, `chunks`;
  - `DataTable`, `PasswordDialog`, `PageHeader`, `GroupChecklist`, `formatBytes`, `formatDateTime`.
- Produces:
  - the `/admin/documents` page;
  - `StatusBadge({status})`, `latestVersion(doc)` and `isProcessing(status)`, all exported from `document-sheet.tsx`.
- Query keys: `["admin","documents",collectionId,showDeleted]`, `["admin","document",id]`, `["admin","chunks",documentId,versionId]`.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/documents/page.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import DocumentsPage from "@/app/admin/documents/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const collection = {
  id: "c1",
  name: "Policies",
  description: "",
  sensitive: false,
  groups: [{ id: "g1", name: "hr", description: "" }],
  created_at: "2026-10-01T00:00:00Z",
}
const version = (status: string) => ({
  id: "v1",
  version_no: 1,
  status,
  failed_stage: status === "failed" ? "parsing" : null,
  error: status === "failed" ? "Docling could not read the file" : null,
  chunk_count: 12,
  page_count: 3,
  content_type: "application/pdf",
  size_bytes: 2048,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
})
const doc = (status: string) => ({
  id: "d1",
  collection_id: "c1",
  filename: "leave.pdf",
  current_version_id: "v1",
  deleted_at: null,
  restricted_groups: [],
  versions: [version(status)],
  created_at: "2026-10-01T00:00:00Z",
})

function mockApi(status = "ready") {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (url === "/api/admin/collections") return jsonResponse([collection])
    if (url === "/api/admin/collections/c1/documents" && init?.method === "POST")
      return jsonResponse([
        { filename: "a.pdf", outcome: "queued", message: "", document_id: "d2", version_id: "v2" },
        {
          filename: "b.pdf",
          outcome: "duplicate",
          message: "This file is already in the collection",
          document_id: "d1",
          version_id: null,
        },
      ])
    if (url.startsWith("/api/admin/collections/c1/documents")) return jsonResponse([doc(status)])
    if (url.includes("/chunks")) return jsonResponse([])
    if (url.startsWith("/api/admin/versions/")) return jsonResponse(version("queued"))
    if (url.startsWith("/api/admin/documents/d1")) return jsonResponse(doc(status))
    return jsonResponse([])
  })
}

const calls = (fetchMock: ReturnType<typeof mockApi>, method: string, url: string) =>
  fetchMock.mock.calls.filter(([u, i]) => String(u) === url && i?.method === method)

describe("DocumentsPage", () => {
  it("uploads files and reports duplicates", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<DocumentsPage />)
    expect(await screen.findByRole("button", { name: "leave.pdf" })).toBeInTheDocument()
    const files = [
      new File(["%PDF-1"], "a.pdf", { type: "application/pdf" }),
      new File(["%PDF-1"], "b.pdf", { type: "application/pdf" }),
    ]
    await userEvent.upload(screen.getByLabelText("Upload files"), files)
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/admin/collections/c1/documents")).toHaveLength(1)
    )
    const body = calls(fetchMock, "POST", "/api/admin/collections/c1/documents")[0][1]?.body
    expect((body as FormData).getAll("files")).toHaveLength(2)
    expect(await screen.findByText(/b\.pdf: This file is already in the collection/)).toBeInTheDocument()
  })

  it("deletes a document after password confirmation", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<DocumentsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "leave.pdf" }))
    const sheet = await screen.findByRole("dialog")
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete" }))
    await userEvent.type(await screen.findByLabelText("Your password"), "pw-123")
    await userEvent.click(screen.getByRole("button", { name: "Delete document" }))
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/admin/documents/d1/delete")).toHaveLength(1)
    )
    expect(
      JSON.parse(String(calls(fetchMock, "POST", "/api/admin/documents/d1/delete")[0][1]?.body))
    ).toEqual({ password: "pw-123" })
  })

  it("shows a failed version's error and retries it", async () => {
    const fetchMock = mockApi("failed")
    renderWithProviders(<DocumentsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "leave.pdf" }))
    const sheet = await screen.findByRole("dialog")
    expect(await within(sheet).findByText(/Docling could not read the file/)).toBeInTheDocument()
    await userEvent.click(within(sheet).getByRole("button", { name: "Retry" }))
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/admin/versions/v1/retry")).toHaveLength(1)
    )
  })
})
```

Run: `npm test -- app/admin/documents`
Expected: FAIL.

- [ ] **Step 2: Write the document sheet**

`frontend/components/admin/document-sheet.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatBytes, formatDateTime } from "@/lib/format"
import type { AdminCollection, AdminDocument, VersionStatus } from "@/lib/types"

const DONE: VersionStatus[] = ["ready", "failed", "rejected"]
export const isProcessing = (status: VersionStatus) => !DONE.includes(status)

/** The newest version: what the admin is waiting on (it may not be current yet). */
export const latestVersion = (doc: AdminDocument) =>
  [...doc.versions].sort((a, b) => b.version_no - a.version_no)[0]

export function StatusBadge({ status }: { status: VersionStatus }) {
  if (status === "ready") return <Badge variant="secondary">Ready</Badge>
  if (status === "failed" || status === "rejected")
    return <Badge variant="destructive">{status === "failed" ? "Failed" : "Rejected"}</Badge>
  return <Badge variant="outline">{status[0].toUpperCase() + status.slice(1)}…</Badge>
}

const errorText = (error: unknown) =>
  error instanceof ApiError ? error.message : "Something went wrong. Try again."

export function DocumentSheet({
  documentId,
  collection,
  onOpenChange,
}: {
  documentId: string | null
  collection: AdminCollection | undefined
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [deleting, setDeleting] = useState(false)
  const [filter, setFilter] = useState("")
  const [access, setAccess] = useState<string[]>([])

  const { data: doc } = useQuery({
    queryKey: ["admin", "document", documentId],
    queryFn: () => adminApi.document(documentId!),
    enabled: !!documentId,
    refetchInterval: (query) => {
      const latest = query.state.data && latestVersion(query.state.data)
      return latest && isProcessing(latest.status) ? 5000 : false
    },
  })
  const current = doc?.versions.find((v) => v.id === doc.current_version_id)
  const chunks = useQuery({
    queryKey: ["admin", "chunks", documentId, current?.id],
    queryFn: () => adminApi.chunks(documentId!, current!.id),
    enabled: !!documentId && current?.status === "ready",
  })

  useEffect(() => {
    setAccess(doc?.restricted_groups.map((g) => g.id) ?? [])
  }, [doc])

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "document", documentId] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "documents"] })
  }
  const retry = useMutation({
    mutationFn: adminApi.retryVersion,
    onSuccess: () => {
      toast.success("Queued for processing again")
      refresh()
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const restore = useMutation({
    mutationFn: () => adminApi.restoreDocument(documentId!),
    onSuccess: () => {
      toast.success("Document restored")
      refresh()
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const saveAccess = useMutation({
    mutationFn: () => adminApi.setDocumentGroups(documentId!, access),
    onSuccess: () => {
      toast.success("Access updated")
      refresh()
    },
    onError: (e) => toast.error(errorText(e)),
  })

  const needle = filter.trim().toLowerCase()
  const shownChunks = (chunks.data ?? []).filter(
    (c) => !needle || c.text.toLowerCase().includes(needle)
  )

  return (
    <Sheet open={!!documentId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{doc?.filename ?? "Document"}</SheetTitle>
          <SheetDescription>
            {doc?.deleted_at
              ? `Deleted ${formatDateTime(doc.deleted_at)}; restorable for 30 days.`
              : collection?.name}
          </SheetDescription>
        </SheetHeader>
        {doc && (
          <div className="grid gap-6 px-4 pb-6">
            <section className="grid gap-2">
              <h3 className="text-sm font-medium">Versions</h3>
              {[...doc.versions]
                .sort((a, b) => b.version_no - a.version_no)
                .map((v) => (
                  <div key={v.id} className="grid gap-1 rounded-md border p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">v{v.version_no}</span>
                      <StatusBadge status={v.status} />
                      {v.id === doc.current_version_id && <Badge variant="outline">Current</Badge>}
                      <span className="text-muted-foreground">
                        {v.chunk_count} chunks · {v.page_count ?? "—"} pages ·{" "}
                        {formatBytes(v.size_bytes)} · {formatDateTime(v.created_at)}
                      </span>
                      {v.status === "failed" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="ml-auto"
                          disabled={retry.isPending}
                          onClick={() => retry.mutate(v.id)}
                        >
                          Retry
                        </Button>
                      )}
                    </div>
                    {v.error && (
                      <p className="text-destructive">
                        {v.failed_stage ? `${v.failed_stage}: ` : ""}
                        {v.error}
                      </p>
                    )}
                  </div>
                ))}
            </section>
            <Separator />
            <section className="grid gap-2">
              <h3 className="text-sm font-medium">Access</h3>
              <p className="text-sm text-muted-foreground">
                Leave all unchecked to give every group of the collection access, or pick a
                subset to restrict this document further.
              </p>
              <GroupChecklist
                groups={collection?.groups ?? []}
                value={access}
                onChange={setAccess}
                idPrefix="doc-group"
              />
              <div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={saveAccess.isPending}
                  onClick={() => saveAccess.mutate()}
                >
                  Save access
                </Button>
              </div>
            </section>
            <Separator />
            <section className="grid gap-2">
              <h3 className="text-sm font-medium">Chunks</h3>
              {current?.status !== "ready" ? (
                <p className="text-sm text-muted-foreground">
                  Chunks appear when the current version is ready.
                </p>
              ) : (
                <>
                  <Input
                    aria-label="Filter chunks"
                    placeholder="Filter chunks"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {shownChunks.length} of {chunks.data?.length ?? 0} chunks
                  </p>
                  {shownChunks.map((chunk) => (
                    <div key={chunk.position} className="rounded-md border p-3 text-sm">
                      <div className="mb-1 text-xs text-muted-foreground">
                        #{chunk.position} · {chunk.modality}
                        {chunk.page !== null && ` · page ${chunk.page}`}
                        {chunk.heading_path.length > 0 && ` · ${chunk.heading_path.join(" › ")}`}
                      </div>
                      <pre className="font-sans whitespace-pre-wrap">{chunk.text}</pre>
                    </div>
                  ))}
                </>
              )}
            </section>
            <Separator />
            <section className="flex gap-2">
              {doc.deleted_at ? (
                <Button disabled={restore.isPending} onClick={() => restore.mutate()}>
                  Restore
                </Button>
              ) : (
                <Button variant="destructive" onClick={() => setDeleting(true)}>
                  Delete
                </Button>
              )}
            </section>
          </div>
        )}
        <PasswordDialog
          open={deleting}
          onOpenChange={setDeleting}
          title={`Delete ${doc?.filename ?? "document"}?`}
          description="It disappears from answers at once and can be restored for 30 days."
          confirmLabel="Delete document"
          destructive
          onConfirm={async (password) => {
            await adminApi.deleteDocument(documentId!, password)
            toast.success("Document deleted")
            refresh()
          }}
        />
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 3: Write the documents page**

`frontend/app/admin/documents/page.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { UploadIcon } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import {
  DocumentSheet,
  StatusBadge,
  isProcessing,
  latestVersion,
} from "@/components/admin/document-sheet"
import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatBytes, formatDateTime } from "@/lib/format"
import type { AdminDocument, UploadResult } from "@/lib/types"

// Mirrors backend/app/documents/filetypes.py EXTENSIONS.
const ACCEPT =
  ".pdf,.docx,.pptx,.xlsx,.csv,.md,.markdown,.txt,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff"

export default function DocumentsPage() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const collections = useQuery({ queryKey: ["admin", "collections"], queryFn: adminApi.collections })
  const [chosen, setChosen] = useState<string | null>(null)
  const collectionId = chosen ?? collections.data?.[0]?.id ?? null
  const collection = collections.data?.find((c) => c.id === collectionId)
  const [showDeleted, setShowDeleted] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [problems, setProblems] = useState<UploadResult[]>([])

  const documents = useQuery({
    queryKey: ["admin", "documents", collectionId, showDeleted],
    queryFn: () => adminApi.documents(collectionId!, showDeleted),
    enabled: !!collectionId,
    refetchInterval: (query) =>
      query.state.data?.some((d) => isProcessing(latestVersion(d).status)) ? 5000 : false,
  })

  const upload = useMutation({
    mutationFn: (files: File[]) => adminApi.uploadDocuments(collectionId!, files),
    onSuccess: (results) => {
      const queued = results.filter((r) => r.outcome === "queued").length
      setProblems(results.filter((r) => r.outcome !== "queued" || r.message))
      toast.success(`${queued} of ${results.length} files queued for processing`)
      void queryClient.invalidateQueries({ queryKey: ["admin", "documents"] })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  })

  const columns: ColumnDef<AdminDocument>[] = [
    {
      accessorKey: "filename",
      header: "File",
      enableSorting: true,
      cell: ({ row }) => (
        <Button
          variant="link"
          className="h-auto p-0 font-medium"
          onClick={() => setOpenId(row.original.id)}
        >
          {row.original.filename}
        </Button>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: ({ row }) =>
        row.original.deleted_at ? (
          <span className="text-muted-foreground">Deleted</span>
        ) : (
          <StatusBadge status={latestVersion(row.original).status} />
        ),
    },
    {
      id: "chunks",
      header: "Chunks",
      cell: ({ row }) => latestVersion(row.original).chunk_count,
    },
    {
      id: "pages",
      header: "Pages",
      cell: ({ row }) => latestVersion(row.original).page_count ?? "—",
    },
    {
      id: "size",
      header: "Size",
      cell: ({ row }) => formatBytes(latestVersion(row.original).size_bytes),
    },
    {
      id: "access",
      header: "Access",
      cell: ({ row }) =>
        row.original.restricted_groups.length
          ? row.original.restricted_groups.map((g) => g.name).join(", ")
          : "Whole collection",
    },
    {
      id: "updated",
      header: "Updated",
      cell: ({ row }) => formatDateTime(latestVersion(row.original).updated_at),
    },
  ]

  return (
    <>
      <PageHeader
        title="Documents"
        description="Upload files; they are scanned, parsed and indexed in the background."
        actions={
          <>
            <NativeSelect
              aria-label="Collection"
              value={collectionId ?? ""}
              onChange={(e) => setChosen(e.target.value)}
            >
              {collections.data?.map((c) => (
                <NativeSelectOption key={c.id} value={c.id}>
                  {c.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              aria-label="Upload files"
              className="sr-only"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                e.target.value = ""
                if (files.length) upload.mutate(files)
              }}
            />
            <Button
              disabled={!collectionId || upload.isPending}
              onClick={() => fileInput.current?.click()}
            >
              <UploadIcon /> {upload.isPending ? "Uploading…" : "Upload"}
            </Button>
          </>
        }
      />
      {collections.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Create a collection first (Collections &amp; access).
        </p>
      )}
      {problems.length > 0 && (
        <ul className="mb-4 grid gap-1 rounded-md border p-3 text-sm" aria-label="Upload problems">
          {problems.map((p) => (
            <li key={p.filename}>
              {p.filename}: {p.message || p.outcome}
            </li>
          ))}
        </ul>
      )}
      <div className="mb-3 flex items-center gap-2">
        <Switch id="show-deleted" checked={showDeleted} onCheckedChange={setShowDeleted} />
        <Label htmlFor="show-deleted">Show deleted</Label>
      </div>
      <DataTable
        columns={columns}
        data={documents.data ?? []}
        isLoading={documents.isLoading && !!collectionId}
        getRowId={(d) => d.id}
        empty="No documents in this collection yet."
      />
      <DocumentSheet
        documentId={openId}
        collection={collection}
        onOpenChange={(open) => !open && setOpenId(null)}
      />
    </>
  )
}
```

- [ ] **Step 4: Run the tests and checks**

Run: `npm test -- app/admin && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/admin/documents frontend/components/admin/document-sheet.tsx
git commit -m "feat(admin): documents page with upload, live status, versions, access and chunk inspector"
```

---

### Task 8: Review queue and audit log

**Files:**
- Create: `frontend/app/admin/review/page.tsx`, `frontend/components/admin/review-sheet.tsx`, `frontend/app/admin/audit/page.tsx`
- Test: `frontend/app/admin/review/page.test.tsx`, `frontend/app/admin/audit/page.test.tsx`

**Interfaces:**
- Consumes:
  - `adminApi`: `reviewQueue`, `reviewMessage`, `markReviewed`, `addToEvalSet`, `evalSets`, `audit`, `auditExportUrl`;
  - `Markdown` from `@/components/chat/markdown` (sanitized);
  - `DataTable`, `PageHeader`, `formatDateTime`.
- Produces:
  - the `/admin/review` and `/admin/audit` pages;
  - `traceUrl(traceId) -> string | null` in `lib/config.ts`, built from `NEXT_PUBLIC_PHOENIX_URL` (Task 9 uses it for eval results).
- Query keys: `["admin","review",kind,includeReviewed,page]`, `["admin","review-message",id]`, `["admin","eval-sets"]`, `["admin","audit",filters]`.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/review/page.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import ReviewPage from "@/app/admin/review/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const item = {
  kind: "feedback",
  id: "m1",
  created_at: "2026-10-08T10:00:00Z",
  user_id: "u2",
  username: "bob",
  message_id: "m1",
  question: "How many leave days?",
  answer: "Twenty [1]",
  detail: { rating: -1, comment: "Wrong number" },
  reviewed_at: null,
}
const detail = {
  conversation_id: "c9",
  user: { id: "u2", username: "bob" },
  question: "How many leave days?",
  answer: {
    id: "m1",
    content: "Employees get **twenty** days <script>alert(1)</script>",
    outcome: "answered",
    sources: [],
    citations: [],
    low_confidence: false,
    guardrail: null,
    feedback_rating: -1,
    feedback_comment: "Wrong number",
    trace_id: "abc123",
    created_at: "2026-10-08T10:00:00Z",
  },
}

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (init?.method === "POST") return jsonResponse(null, url.endsWith("/reviewed") ? 204 : 201)
    if (url.startsWith("/api/admin/review-queue/messages/m1")) return jsonResponse(detail)
    if (url === "/api/admin/eval-sets")
      return jsonResponse([{ id: "s1", name: "Core", description: "", case_count: 3, created_at: "" }])
    return jsonResponse([item])
  })
}

describe("ReviewPage", () => {
  it("marks an item reviewed", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<ReviewPage />)
    expect(await screen.findByText("Wrong number")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, i]) =>
            String(u) === "/api/admin/review-queue/feedback/m1/reviewed" && i?.method === "POST"
        )
      ).toBe(true)
    )
  })

  it("opens the conversation safely and adds it to a test set", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<ReviewPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Open" }))
    const sheet = await screen.findByRole("dialog")
    expect(await within(sheet).findByText("twenty")).toBeInTheDocument()
    expect(sheet.querySelector("script")).toBeNull()
    await userEvent.selectOptions(within(sheet).getByLabelText("Test set"), "s1")
    await userEvent.type(within(sheet).getByLabelText("Expected answer"), "Twenty-five days")
    await userEvent.click(within(sheet).getByRole("button", { name: "Add to test set" }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/add-to-eval-set"))
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        eval_set_id: "s1",
        expected_answer: "Twenty-five days",
        unanswerable: false,
      })
    })
  })
})
```

`frontend/app/admin/audit/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import AuditPage from "@/app/admin/audit/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const entry = (id: number) => ({
  id,
  created_at: "2026-10-08T10:00:00Z",
  actor_id: "u1",
  actor_username: "root",
  action: "user.created",
  target_type: "user",
  target_id: `u${id}`,
  detail: { role: "user" },
  request_id: "req-1",
})

describe("AuditPage", () => {
  it("filters, pages back and exports with the same filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes("before_id=51")) return jsonResponse([entry(50)])
      if (url.includes("action=user.")) return jsonResponse(
        Array.from({ length: 50 }, (_, i) => entry(100 - i))
      )
      return jsonResponse([entry(1)])
    })
    renderWithProviders(<AuditPage />)
    await screen.findByText("u1")
    await userEvent.type(screen.getByLabelText("Action starts with"), "user.")
    await userEvent.click(screen.getByRole("button", { name: "Apply" }))
    await screen.findByText("u100")
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/admin/audit/export?action=user."
    )
    await userEvent.click(screen.getByRole("button", { name: "Load older entries" }))
    await screen.findByText("u50")
    expect(
      fetchMock.mock.calls.some(([u]) => String(u) === "/api/admin/audit?action=user.&before_id=51&limit=50")
    ).toBe(true)
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Load older entries" })).toBeNull()
    )
  })
})
```

Run: `npm test -- app/admin/review app/admin/audit`
Expected: FAIL.

- [ ] **Step 2: Add the trace link helper**

Append to `frontend/lib/config.ts`:

```ts
const PHOENIX_URL = process.env.NEXT_PUBLIC_PHOENIX_URL?.replace(/\/+$/, "")

/** Link to a trace in Phoenix (spec §7.2), or null when Phoenix's URL isn't configured. */
export const traceUrl = (traceId: string | null) =>
  PHOENIX_URL && traceId ? `${PHOENIX_URL}/redirects/traces/${encodeURIComponent(traceId)}` : null
```

- [ ] **Step 3: Write the review sheet**

`frontend/components/admin/review-sheet.tsx`:

```tsx
"use client"

import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Markdown } from "@/components/chat/markdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { traceUrl } from "@/lib/config"
import { formatDateTime } from "@/lib/format"

/** One answer under review. Opening it is audited by the backend (spec §6.6). */
export function ReviewSheet({
  messageId,
  onOpenChange,
}: {
  messageId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const { data, isError } = useQuery({
    queryKey: ["admin", "review-message", messageId],
    queryFn: () => adminApi.reviewMessage(messageId!),
    enabled: !!messageId,
  })
  const sets = useQuery({
    queryKey: ["admin", "eval-sets"],
    queryFn: adminApi.evalSets,
    enabled: !!messageId,
  })
  const [setId, setSetId] = useState("")
  const [expected, setExpected] = useState("")
  const [unanswerable, setUnanswerable] = useState(false)
  const add = useMutation({
    mutationFn: () =>
      adminApi.addToEvalSet(messageId!, {
        eval_set_id: setId,
        expected_answer: expected.trim() || null,
        unanswerable,
      }),
    onSuccess: () => {
      toast.success("Added to the test set")
      setExpected("")
      setUnanswerable(false)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not add the case"),
  })
  const answer = data?.answer
  const trace = traceUrl(answer?.trace_id ?? null)

  return (
    <Sheet open={!!messageId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>Answer review</SheetTitle>
          <SheetDescription>
            {data ? `${data.user.username} · ${formatDateTime(data.answer.created_at)}` : ""}
          </SheetDescription>
        </SheetHeader>
        {isError && <p className="px-4 text-sm text-destructive">Could not load this answer.</p>}
        {data && answer && (
          <div className="grid gap-4 px-4 pb-6 text-sm">
            <section>
              <h3 className="mb-1 font-medium">Question</h3>
              <p className="whitespace-pre-wrap">{data.question ?? "—"}</p>
            </section>
            <section>
              <h3 className="mb-1 font-medium">Answer</h3>
              <div className="mb-2 flex flex-wrap gap-1">
                {answer.outcome && <Badge variant="outline">{answer.outcome}</Badge>}
                {answer.low_confidence && <Badge variant="destructive">Low confidence</Badge>}
                {answer.feedback_rating === -1 && <Badge variant="destructive">👎</Badge>}
                {answer.feedback_rating === 1 && <Badge variant="secondary">👍</Badge>}
              </div>
              <Markdown content={answer.content} sources={answer.citations} onOpenSource={() => {}} />
              {answer.feedback_comment && (
                <p className="mt-2 text-muted-foreground">
                  Comment: {answer.feedback_comment}
                </p>
              )}
            </section>
            {answer.sources.length > 0 && (
              <section>
                <h3 className="mb-1 font-medium">Sources</h3>
                <ol className="list-decimal pl-5">
                  {answer.sources.map((s) => (
                    <li key={`${s.n}-${s.doc_id}`}>
                      {s.filename}
                      {s.page !== null && `, page ${s.page}`} · score {s.score.toFixed(2)}
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {answer.guardrail && (
              <section>
                <h3 className="mb-1 font-medium">Guardrail</h3>
                <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
                  {JSON.stringify(answer.guardrail, null, 2)}
                </pre>
              </section>
            )}
            <p className="text-muted-foreground">
              Trace:{" "}
              {trace ? (
                <a className="underline" href={trace} target="_blank" rel="noreferrer">
                  open in Phoenix
                </a>
              ) : (
                (answer.trace_id ?? "—")
              )}
            </p>
            <Separator />
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault()
                add.mutate()
              }}
            >
              <h3 className="font-medium">Add to a test set</h3>
              <Field>
                <FieldLabel htmlFor="review-set">Test set</FieldLabel>
                <NativeSelect
                  id="review-set"
                  value={setId}
                  onChange={(e) => setSetId(e.target.value)}
                >
                  <NativeSelectOption value="">Choose a test set</NativeSelectOption>
                  {sets.data?.map((s) => (
                    <NativeSelectOption key={s.id} value={s.id}>
                      {s.name}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="review-expected">Expected answer</FieldLabel>
                <Textarea
                  id="review-expected"
                  rows={3}
                  value={expected}
                  onChange={(e) => setExpected(e.target.value)}
                />
              </Field>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="review-unanswerable"
                  checked={unanswerable}
                  onCheckedChange={(v) => setUnanswerable(v === true)}
                />
                <Label htmlFor="review-unanswerable">
                  The documents can&apos;t answer this (expect &ldquo;I don&apos;t know&rdquo;)
                </Label>
              </div>
              <div>
                <Button type="submit" disabled={!setId || add.isPending}>
                  Add to test set
                </Button>
              </div>
            </form>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
```

The add-to-set form uses plain state, not react-hook-form (see the ruling on small forms): it has no validation beyond "a set is chosen", and the backend validates the rest.

- [ ] **Step 4: Write the review page**

`frontend/app/admin/review/page.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useState } from "react"
import { toast } from "sonner"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { ReviewSheet } from "@/components/admin/review-sheet"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { ReviewItem, ReviewKind } from "@/lib/types"

const KIND_LABELS: Record<ReviewKind, string> = {
  feedback: "👎 Feedback",
  low_confidence: "Low confidence",
  guardrail: "Guardrail",
}
const PAGE = 50

function summary(item: ReviewItem): string {
  const d = item.detail
  if (item.kind === "feedback") return String(d.comment ?? "No comment")
  if (item.kind === "guardrail")
    return [d.check, d.category, d.action].filter(Boolean).map(String).join(" · ")
  return "Answer may not be supported by its sources"
}

export default function ReviewPage() {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<ReviewKind | "all">("all")
  const [includeReviewed, setIncludeReviewed] = useState(false)
  const [page, setPage] = useState(0)
  const [openMessage, setOpenMessage] = useState<string | null>(null)
  const queue = useQuery({
    queryKey: ["admin", "review", kind, includeReviewed, page],
    queryFn: () =>
      adminApi.reviewQueue(kind === "all" ? undefined : kind, includeReviewed, page * PAGE),
  })
  const mark = useMutation({
    mutationFn: (item: ReviewItem) => adminApi.markReviewed(item.kind, item.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "review"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not update"),
  })

  const columns: ColumnDef<ReviewItem>[] = [
    { id: "when", header: "When", cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: "kind",
      header: "Kind",
      cell: ({ row }) => <Badge variant="outline">{KIND_LABELS[row.original.kind]}</Badge>,
    },
    { accessorKey: "username", header: "User" },
    {
      id: "question",
      header: "Question",
      cell: ({ row }) => (
        <span className="line-clamp-2 max-w-sm">{row.original.question ?? "—"}</span>
      ),
    },
    { id: "detail", header: "Detail", cell: ({ row }) => summary(row.original) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex gap-2">
          {row.original.message_id && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setOpenMessage(row.original.message_id)}
            >
              Open
            </Button>
          )}
          {!row.original.reviewed_at && (
            <Button
              size="sm"
              variant="ghost"
              disabled={mark.isPending}
              onClick={() => mark.mutate(row.original)}
            >
              Mark reviewed
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Review queue"
        description="👎 answers, low-confidence answers and guardrail flags. Opening an answer is audited."
      />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          value={kind}
          onValueChange={(value) => {
            setKind(value as ReviewKind | "all")
            setPage(0)
          }}
        >
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {(Object.keys(KIND_LABELS) as ReviewKind[]).map((k) => (
              <TabsTrigger key={k} value={k}>
                {KIND_LABELS[k]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          <Switch
            id="include-reviewed"
            checked={includeReviewed}
            onCheckedChange={(v) => {
              setIncludeReviewed(v)
              setPage(0)
            }}
          />
          <Label htmlFor="include-reviewed">Include reviewed</Label>
        </div>
      </div>
      <DataTable
        columns={columns}
        data={queue.data ?? []}
        isLoading={queue.isLoading}
        getRowId={(i) => `${i.kind}-${i.id}`}
        empty="Nothing to review."
      />
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={(queue.data?.length ?? 0) < PAGE}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
      <ReviewSheet
        messageId={openMessage}
        onOpenChange={(open) => !open && setOpenMessage(null)}
      />
    </>
  )
}
```

The review list is audited server-side on every fetch, so `refetchOnWindowFocus` stays off (the app default).

- [ ] **Step 5: Write the audit page**

`frontend/app/admin/audit/page.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useInfiniteQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { DownloadIcon } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { adminApi } from "@/lib/admin-api"
import { formatDateTime } from "@/lib/format"
import type { AuditEntry, AuditFilters } from "@/lib/types"

const PAGE = 50
const schema = z.object({
  actor: z.string().max(64),
  action: z.string().max(100),
  target_type: z.string().max(50),
  target_id: z.string().max(100),
  since: z.string(),
  until: z.string(),
})
type Values = z.infer<typeof schema>
const EMPTY: Values = { actor: "", action: "", target_type: "", target_id: "", since: "", until: "" }

/** Local calendar days to an inclusive [since, until) range in UTC ISO strings. */
function toFilters(values: Values): AuditFilters {
  const filters: AuditFilters = {}
  for (const key of ["actor", "action", "target_type", "target_id"] as const) {
    const value = values[key].trim()
    if (value) filters[key] = value
  }
  if (values.since) filters.since = new Date(`${values.since}T00:00:00`).toISOString()
  if (values.until) {
    const end = new Date(`${values.until}T00:00:00`)
    end.setDate(end.getDate() + 1)
    filters.until = end.toISOString()
  }
  return filters
}

const columns: ColumnDef<AuditEntry>[] = [
  { id: "when", header: "When", cell: ({ row }) => formatDateTime(row.original.created_at) },
  { id: "actor", header: "Actor", cell: ({ row }) => row.original.actor_username ?? "system" },
  { accessorKey: "action", header: "Action" },
  {
    id: "target",
    header: "Target",
    cell: ({ row }) =>
      row.original.target_id ? (
        <span>
          <span className="text-muted-foreground">{row.original.target_type}</span>{" "}
          {row.original.target_id}
        </span>
      ) : (
        "—"
      ),
  },
  {
    id: "detail",
    header: "Details",
    cell: ({ row }) => (
      <code className="line-clamp-2 max-w-md text-xs break-all">
        {JSON.stringify(row.original.detail)}
      </code>
    ),
  },
  {
    id: "request",
    header: "Request",
    cell: ({ row }) => (
      <code className="text-xs text-muted-foreground">{row.original.request_id ?? "—"}</code>
    ),
  },
]

const LABELS: Record<keyof Values, string> = {
  actor: "Actor username",
  action: "Action starts with",
  target_type: "Target type",
  target_id: "Target id",
  since: "From",
  until: "To",
}

export default function AuditPage() {
  const [filters, setFilters] = useState<AuditFilters>({})
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY })
  const audit = useInfiniteQuery({
    queryKey: ["admin", "audit", filters],
    queryFn: ({ pageParam }) => adminApi.audit(filters, pageParam, PAGE),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].id : undefined),
  })
  const rows = audit.data?.pages.flat() ?? []

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every sign-in, change and admin view. Entries can't be edited or deleted."
        actions={
          <Button variant="outline" asChild>
            <a href={adminApi.auditExportUrl(filters)} download>
              <DownloadIcon /> Export CSV
            </a>
          </Button>
        }
      />
      <form
        className="mb-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6"
        onSubmit={form.handleSubmit((values) => setFilters(toFilters(values)))}
      >
        {(Object.keys(LABELS) as (keyof Values)[]).map((key) => (
          <Field key={key}>
            <FieldLabel htmlFor={`audit-${key}`}>{LABELS[key]}</FieldLabel>
            <Input
              id={`audit-${key}`}
              type={key === "since" || key === "until" ? "date" : "text"}
              {...form.register(key)}
            />
          </Field>
        ))}
        <div className="flex gap-2 sm:col-span-3 lg:col-span-6">
          <Button type="submit">Apply</Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              form.reset(EMPTY)
              setFilters({})
            }}
          >
            Clear
          </Button>
        </div>
      </form>
      <DataTable
        columns={columns}
        data={rows}
        isLoading={audit.isLoading}
        getRowId={(e) => String(e.id)}
        empty="No entries match."
      />
      {audit.hasNextPage && (
        <div className="mt-3 flex justify-center">
          <Button
            variant="outline"
            disabled={audit.isFetchingNextPage}
            onClick={() => void audit.fetchNextPage()}
          >
            Load older entries
          </Button>
        </div>
      )}
    </>
  )
}
```

The `qs` helper skips the `undefined` `before_id` on the first page. Key order in the URL follows `{...filters, before_id, limit}`, which the test's exact URL relies on.

- [ ] **Step 6: Run the tests and checks**

Run: `npm test -- app/admin && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/config.ts frontend/app/admin/review frontend/app/admin/audit frontend/components/admin/review-sheet.tsx
git commit -m "feat(admin): review queue with audited answer view and add-to-test-set; audit log with filters and csv export"
```

---
### Task 9: Evaluation — test sets, cases, CSV import, runs, run detail, compare

**Files:**
- Create: `frontend/app/admin/evaluation/page.tsx`, `frontend/app/admin/evaluation/sets/[id]/page.tsx`, `frontend/app/admin/evaluation/runs/[id]/page.tsx`, `frontend/app/admin/evaluation/compare/page.tsx`
- Create: `frontend/components/admin/case-dialog.tsx`, `frontend/components/admin/compare-view.tsx`, `frontend/components/admin/run-summary.tsx`
- Test: `frontend/app/admin/evaluation/page.test.tsx`, `frontend/app/admin/evaluation/sets/[id]/page.test.tsx`, `frontend/components/admin/compare-view.test.tsx`

**Interfaces:**
- Consumes:
  - `adminApi`: `evalSets`, `evalSet`, `createEvalSet`, `deleteEvalSet`, `evalCases`, `createCase`, `deleteCase`, `importCases`, `evalRuns`, `evalRun`, `startRun`, `compareRuns`, `ragConfigs`, `groups`, `collections`;
  - `traceUrl`, `isSuperAdmin`, `DataTable`, `PageHeader`, `GroupChecklist`, `formatPercent`, `formatUsd`, `formatDateTime`.
- Produces:
  - the `/admin/evaluation`, `/admin/evaluation/sets/[id]`, `/admin/evaluation/runs/[id]` and `/admin/evaluation/compare?a=&b=` pages;
  - `METRIC_LABELS`, `RunStatusBadge({status})` and `RunSummary({summary})`, exported from `run-summary.tsx`.
- Query keys: `["admin","eval-sets"]`, `["admin","eval-set",id]`, `["admin","eval-cases",id]`, `["admin","eval-runs"]`, `["admin","eval-run",id]`, `["admin","compare",a,b]`.
- Ruling: admins (not super admins) can run evals but can't list RagConfig versions, because that API is super_admin only. The run form therefore offers "Active configuration" to everyone, and lists versions only for super admins.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/evaluation/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import EvaluationPage from "@/app/admin/evaluation/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const set = { id: "s1", name: "Core", description: "", case_count: 4, created_at: "2026-10-01T00:00:00Z" }
const run = {
  id: "r1",
  eval_set_id: "s1",
  rag_config_id: null,
  rag_config_version: 2,
  status: "completed",
  error: null,
  case_count: 4,
  summary: { score: 0.82, idk_accuracy: 1, answered_rate: 0.75, latency_p95_ms: 2100, cost_per_question_usd: 0.003 },
  created_at: "2026-10-08T09:00:00Z",
  started_at: "2026-10-08T09:00:01Z",
  finished_at: "2026-10-08T09:02:00Z",
}

describe("EvaluationPage", () => {
  it("starts a run on the active config without listing versions for admins", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === "/api/auth/me")
        return jsonResponse({ id: "u1", username: "a", full_name: "A", role: "admin", is_active: true, must_change_password: false, groups: [] })
      if (url === "/api/admin/eval-sets") return jsonResponse([set])
      if (init?.method === "POST") return jsonResponse({ ...run, id: "r2", status: "queued" }, 202)
      return jsonResponse([run])
    })
    renderWithProviders(<EvaluationPage />)
    await userEvent.click(await screen.findByRole("tab", { name: "Runs" }))
    expect(await screen.findByText("82%")).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText("Test set"), "s1")
    await userEvent.click(screen.getByRole("button", { name: "Start run" }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u) === "/api/admin/eval-runs" && i?.method === "POST")
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ eval_set_id: "s1", rag_config_id: null })
    })
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/admin/rag-configs"))).toBe(false)
  })
})
```

`frontend/app/admin/evaluation/sets/[id]/page.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import EvalSetPage from "@/app/admin/evaluation/sets/[id]/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "s1" }) }))

const hr = { id: "g1", name: "hr", description: "" }

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (url.endsWith("/import"))
      return jsonResponse({ created: 2, errors: [{ row: 4, message: "question: Field required" }] })
    if (url === "/api/admin/eval-sets/s1/cases" && init?.method === "POST")
      return jsonResponse({ id: "k9" }, 201)
    if (url === "/api/admin/eval-sets/s1")
      return jsonResponse({ id: "s1", name: "Core", description: "", case_count: 0, created_at: "" })
    if (url === "/api/admin/groups") return jsonResponse([hr])
    return jsonResponse([])
  })
}

describe("EvalSetPage", () => {
  it("imports a CSV and shows row errors", async () => {
    mockApi()
    renderWithProviders(<EvalSetPage />)
    await screen.findByRole("heading", { name: "Core" })
    await userEvent.upload(
      screen.getByLabelText("Import CSV"),
      new File(["question\nA?\nB?\n,"], "cases.csv", { type: "text/csv" })
    )
    expect(await screen.findByText("2 cases imported")).toBeInTheDocument()
    expect(screen.getByText("Line 4: question: Field required")).toBeInTheDocument()
  })

  it("adds an unanswerable case run as a group", async () => {
    const fetchMock = mockApi()
    renderWithProviders(<EvalSetPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Add case" }))
    const dialog = await screen.findByRole("dialog")
    await userEvent.type(within(dialog).getByLabelText("Question"), "What is the CEO's salary?")
    await userEvent.click(within(dialog).getByLabelText(/can't answer/))
    await userEvent.click(within(dialog).getByLabelText("hr"))
    await userEvent.click(within(dialog).getByRole("button", { name: "Add case" }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u) === "/api/admin/eval-sets/s1/cases" && i?.method === "POST")
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        question: "What is the CEO's salary?",
        expected_answer: null,
        expected_sources: [],
        collection_ids: [],
        run_as_group_ids: ["g1"],
        unanswerable: true,
      })
    })
  })
})
```

`frontend/components/admin/compare-view.test.tsx`:

```tsx
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CompareView } from "@/components/admin/compare-view"
import { jsonResponse, renderWithProviders } from "@/test/render"

const comparison = {
  a: { id: "r1", summary: { score: 0.9 } },
  b: { id: "r2", summary: { score: 0.7 } },
  deltas: { score: -0.2, faithfulness: -0.3 },
  questions: [
    {
      case_id: "k1",
      question: "Leave days?",
      a: { outcome: "answered", metrics: {}, answer: "25" },
      b: { outcome: "not_found", metrics: {}, answer: "I couldn't find it" },
      regressed: true,
      reasons: ["outcome answered → not_found"],
    },
    {
      case_id: "k2",
      question: "Office hours?",
      a: { outcome: "answered", metrics: {}, answer: "9-5" },
      b: { outcome: "answered", metrics: {}, answer: "9-5" },
      regressed: false,
      reasons: [],
    },
  ],
}

describe("CompareView", () => {
  it("highlights regressions and can show only them", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => jsonResponse(comparison))
    renderWithProviders(<CompareView a="r1" b="r2" />)
    expect(await screen.findByText("outcome answered → not_found")).toBeInTheDocument()
    expect(screen.getByText("-0.20")).toBeInTheDocument()
    expect(screen.getByText("Office hours?")).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText("Only regressions"))
    expect(screen.queryByText("Office hours?")).toBeNull()
  })

  it("asks for two runs when one is missing", () => {
    renderWithProviders(<CompareView a={undefined} b="r2" />)
    expect(screen.getByText("Pick two runs to compare on the Runs tab.")).toBeInTheDocument()
  })
})
```

Run: `npm test -- app/admin/evaluation components/admin/compare-view`
Expected: FAIL.

- [ ] **Step 2: Shared run pieces**

`frontend/components/admin/run-summary.tsx`:

```tsx
import { Badge } from "@/components/ui/badge"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { formatPercent, formatUsd } from "@/lib/format"
import type { RunStatus, RunSummary as Summary } from "@/lib/types"

export const METRIC_LABELS: Record<string, string> = {
  score: "Score",
  hit_rate: "Hit rate",
  context_precision: "Context precision",
  context_recall: "Context recall",
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevance",
  answer_correctness: "Correctness",
  idk_accuracy: "“I don’t know” accuracy",
  answered_rate: "Answered rate",
  latency_p95_ms: "Latency p95 (ms)",
  cost_per_question_usd: "Cost / question",
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const variant =
    status === "failed" ? "destructive" : status === "completed" ? "secondary" : "outline"
  return <Badge variant={variant}>{status}</Badge>
}

export function RunSummary({ summary }: { summary: Summary }) {
  const cards: [string, string][] = [
    ["Score", formatPercent(summary.score)],
    ...Object.entries(summary.metrics ?? {}).map(
      ([key, value]): [string, string] => [METRIC_LABELS[key] ?? key, formatPercent(value)]
    ),
    [METRIC_LABELS.idk_accuracy, formatPercent(summary.idk_accuracy)],
    [METRIC_LABELS.answered_rate, formatPercent(summary.answered_rate)],
    ["Latency p50 / p95", `${summary.latency_p50_ms ?? "—"} / ${summary.latency_p95_ms ?? "—"} ms`],
    [
      "Cost / question",
      summary.cost_per_question_usd == null ? "—" : formatUsd(summary.cost_per_question_usd),
    ],
    ["Errors", String(summary.errors ?? 0)],
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(([label, value]) => (
        <Card key={label}>
          <CardHeader>
            <CardDescription>{label}</CardDescription>
            <CardTitle className="text-xl tabular-nums">{value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: The evaluation page (test sets and runs)**

`frontend/app/admin/evaluation/page.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import Link from "next/link"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { RunStatusBadge } from "@/components/admin/run-summary"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { formatDateTime, formatPercent, formatUsd } from "@/lib/format"
import { isSuperAdmin } from "@/lib/roles"
import type { EvalRun, EvalSet } from "@/lib/types"

const setSchema = z.object({
  name: z.string().trim().min(1, "Enter a name").max(100),
  description: z.string().max(500),
})

function NewSetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient()
  const form = useForm<z.infer<typeof setSchema>>({
    resolver: zodResolver(setSchema),
    defaultValues: { name: "", description: "" },
  })
  const create = useMutation({
    mutationFn: adminApi.createEvalSet,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-sets"] })
      form.reset()
      onOpenChange(false)
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not create the set"),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form className="grid gap-4" onSubmit={form.handleSubmit((v) => create.mutate(v))}>
          <DialogHeader>
            <DialogTitle>New test set</DialogTitle>
          </DialogHeader>
          <Field data-invalid={!!form.formState.errors.name}>
            <FieldLabel htmlFor="set-name">Name</FieldLabel>
            <Input id="set-name" {...form.register("name")} />
            <FieldError errors={[form.formState.errors.name]} />
          </Field>
          <Field>
            <FieldLabel htmlFor="set-description">Description</FieldLabel>
            <Input id="set-description" {...form.register("description")} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function EvaluationPage() {
  const queryClient = useQueryClient()
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me })
  const superAdmin = !!me && isSuperAdmin(me)
  const sets = useQuery({ queryKey: ["admin", "eval-sets"], queryFn: adminApi.evalSets })
  const runs = useQuery({
    queryKey: ["admin", "eval-runs"],
    queryFn: () => adminApi.evalRuns(),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 5000 : false,
  })
  const versions = useQuery({
    queryKey: ["admin", "rag-configs"],
    queryFn: adminApi.ragConfigs,
    enabled: superAdmin,
  })
  const [newSet, setNewSet] = useState(false)
  const [setId, setSetId] = useState("")
  const [configId, setConfigId] = useState("")
  const [compareA, setCompareA] = useState("")
  const [compareB, setCompareB] = useState("")
  const setName = (id: string) => sets.data?.find((s) => s.id === id)?.name ?? "—"

  const start = useMutation({
    mutationFn: () => adminApi.startRun({ eval_set_id: setId, rag_config_id: configId || null }),
    onSuccess: () => {
      toast.success("Run queued")
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-runs"] })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start the run"),
  })

  const setColumns: ColumnDef<EvalSet>[] = [
    {
      accessorKey: "name",
      header: "Name",
      enableSorting: true,
      cell: ({ row }) => (
        <Link className="font-medium underline-offset-4 hover:underline" href={`/admin/evaluation/sets/${row.original.id}`}>
          {row.original.name}
        </Link>
      ),
    },
    { accessorKey: "description", header: "Description" },
    { accessorKey: "case_count", header: "Cases" },
    { id: "created", header: "Created", cell: ({ row }) => formatDateTime(row.original.created_at) },
  ]
  const runColumns: ColumnDef<EvalRun>[] = [
    {
      id: "created",
      header: "Started",
      cell: ({ row }) => (
        <Link className="underline-offset-4 hover:underline" href={`/admin/evaluation/runs/${row.original.id}`}>
          {formatDateTime(row.original.created_at)}
        </Link>
      ),
    },
    { id: "set", header: "Test set", cell: ({ row }) => setName(row.original.eval_set_id) },
    {
      id: "config",
      header: "Config",
      cell: ({ row }) =>
        row.original.rag_config_version ? `v${row.original.rag_config_version}` : "defaults",
    },
    { id: "status", header: "Status", cell: ({ row }) => <RunStatusBadge status={row.original.status} /> },
    { id: "score", header: "Score", cell: ({ row }) => formatPercent(row.original.summary.score) },
    {
      id: "idk",
      header: "“I don’t know”",
      cell: ({ row }) => formatPercent(row.original.summary.idk_accuracy),
    },
    { id: "answered", header: "Answered", cell: ({ row }) => formatPercent(row.original.summary.answered_rate) },
    {
      id: "p95",
      header: "p95",
      cell: ({ row }) =>
        row.original.summary.latency_p95_ms == null ? "—" : `${row.original.summary.latency_p95_ms} ms`,
    },
    {
      id: "cost",
      header: "Cost / q",
      cell: ({ row }) =>
        row.original.summary.cost_per_question_usd == null
          ? "—"
          : formatUsd(row.original.summary.cost_per_question_usd),
    },
  ]
  const completed = (runs.data ?? []).filter((r) => r.status === "completed")
  const runLabel = (r: EvalRun) =>
    `${formatDateTime(r.created_at)} · ${setName(r.eval_set_id)} · ${r.rag_config_version ? `v${r.rag_config_version}` : "defaults"}`

  return (
    <>
      <PageHeader
        title="Evaluation"
        description="Test sets measure answer quality; compare runs before activating a config."
      />
      <Tabs defaultValue="sets">
        <TabsList>
          <TabsTrigger value="sets">Test sets</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>
        <TabsContent value="sets" className="grid gap-3">
          <div className="flex justify-end">
            <Button onClick={() => setNewSet(true)}>New test set</Button>
          </div>
          <DataTable columns={setColumns} data={sets.data ?? []} isLoading={sets.isLoading} getRowId={(s) => s.id} empty="No test sets yet." />
        </TabsContent>
        <TabsContent value="runs" className="grid gap-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              start.mutate()
            }}
          >
            <Field className="w-56">
              <FieldLabel htmlFor="run-set">Test set</FieldLabel>
              <NativeSelect id="run-set" value={setId} onChange={(e) => setSetId(e.target.value)}>
                <NativeSelectOption value="">Choose a test set</NativeSelectOption>
                {sets.data?.map((s) => (
                  <NativeSelectOption key={s.id} value={s.id}>
                    {s.name} ({s.case_count})
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field className="w-56">
              <FieldLabel htmlFor="run-config">Configuration</FieldLabel>
              <NativeSelect id="run-config" value={configId} onChange={(e) => setConfigId(e.target.value)}>
                <NativeSelectOption value="">Active configuration</NativeSelectOption>
                {versions.data?.map((v) => (
                  <NativeSelectOption key={v.id} value={v.id}>
                    v{v.version}
                    {v.is_active ? " (active)" : ""} {v.note && `– ${v.note}`}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Button type="submit" disabled={!setId || start.isPending}>
              Start run
            </Button>
          </form>
          <DataTable columns={runColumns} data={runs.data ?? []} isLoading={runs.isLoading} getRowId={(r) => r.id} empty="No runs yet." />
          <div className="flex flex-wrap items-end gap-3">
            <Field className="w-72">
              <FieldLabel htmlFor="compare-a">Baseline run (A)</FieldLabel>
              <NativeSelect id="compare-a" value={compareA} onChange={(e) => setCompareA(e.target.value)}>
                <NativeSelectOption value="">Choose a run</NativeSelectOption>
                {completed.map((r) => (
                  <NativeSelectOption key={r.id} value={r.id}>
                    {runLabel(r)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field className="w-72">
              <FieldLabel htmlFor="compare-b">Candidate run (B)</FieldLabel>
              <NativeSelect id="compare-b" value={compareB} onChange={(e) => setCompareB(e.target.value)}>
                <NativeSelectOption value="">Choose a run</NativeSelectOption>
                {completed.map((r) => (
                  <NativeSelectOption key={r.id} value={r.id}>
                    {runLabel(r)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            {compareA && compareB && compareA !== compareB ? (
              <Button variant="outline" asChild>
                <Link href={`/admin/evaluation/compare?a=${compareA}&b=${compareB}`}>Compare</Link>
              </Button>
            ) : (
              <Button variant="outline" disabled>
                Compare
              </Button>
            )}
          </div>
        </TabsContent>
      </Tabs>
      <NewSetDialog open={newSet} onOpenChange={setNewSet} />
    </>
  )
}
```

Run `npm run format` afterwards; several lines are longer than Prettier's width.

- [ ] **Step 4: The case dialog and the set page**

`frontend/components/admin/case-dialog.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Controller, useForm } from "react-hook-form"
import { z } from "zod"

import { GroupChecklist } from "@/components/admin/group-checklist"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { ExpectedSource } from "@/lib/types"

/** "doc-id" or "doc-id:page" per line. */
export function parseSources(text: string): ExpectedSource[] | null {
  const sources: ExpectedSource[] = []
  for (const line of text.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const match = /^([0-9a-f-]{36})(?::(\d+))?$/i.exec(line)
    if (!match) return null
    sources.push({ doc_id: match[1], page: match[2] ? Number(match[2]) : null })
  }
  return sources
}

const schema = z.object({
  question: z.string().trim().min(1, "Enter a question").max(4000),
  expected_answer: z.string().max(8000),
  sources: z.string().refine((v) => parseSources(v) !== null, "One document id per line, optionally :page"),
  collection_ids: z.array(z.string()),
  run_as_group_ids: z.array(z.string()).min(1, "Pick at least one group to ask as"),
  unanswerable: z.boolean(),
})
type Values = z.infer<typeof schema>
const EMPTY: Values = {
  question: "",
  expected_answer: "",
  sources: "",
  collection_ids: [],
  run_as_group_ids: [],
  unanswerable: false,
}

export function CaseDialog({
  setId,
  open,
  onOpenChange,
}: {
  setId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const groups = useQuery({ queryKey: ["admin", "groups"], queryFn: adminApi.groups, enabled: open })
  const collections = useQuery({ queryKey: ["admin", "collections"], queryFn: adminApi.collections, enabled: open })
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY })
  useEffect(() => {
    if (open) {
      setError(null)
      form.reset(EMPTY)
    }
  }, [open, form])
  const create = useMutation({
    mutationFn: (values: Values) =>
      adminApi.createCase(setId, {
        question: values.question,
        expected_answer: values.expected_answer.trim() || null,
        expected_sources: parseSources(values.sources) ?? [],
        collection_ids: values.collection_ids,
        run_as_group_ids: values.run_as_group_ids,
        unanswerable: values.unanswerable,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-cases", setId] })
      void queryClient.invalidateQueries({ queryKey: ["admin", "eval-set", setId] })
      onOpenChange(false)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add the case"),
  })
  const { errors } = form.formState
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto">
        <form className="grid gap-4" onSubmit={form.handleSubmit((v) => create.mutate(v))}>
          <DialogHeader>
            <DialogTitle>Add case</DialogTitle>
            <DialogDescription>
              The question is asked through the real pipeline with the chosen groups&apos; access.
            </DialogDescription>
          </DialogHeader>
          <Field data-invalid={!!errors.question}>
            <FieldLabel htmlFor="case-question">Question</FieldLabel>
            <Textarea id="case-question" rows={2} {...form.register("question")} />
            <FieldError errors={[errors.question]} />
          </Field>
          <Field>
            <FieldLabel htmlFor="case-expected">Expected answer (optional)</FieldLabel>
            <Textarea id="case-expected" rows={2} {...form.register("expected_answer")} />
          </Field>
          <Controller
            control={form.control}
            name="unanswerable"
            render={({ field }) => (
              <div className="flex items-center gap-2">
                <Checkbox id="case-unanswerable" checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} />
                <Label htmlFor="case-unanswerable">The documents can&apos;t answer this</Label>
              </div>
            )}
          />
          <Field data-invalid={!!errors.sources}>
            <FieldLabel htmlFor="case-sources">Expected sources (optional)</FieldLabel>
            <Textarea id="case-sources" rows={2} placeholder="document-id:page" {...form.register("sources")} />
            <FieldDescription>One document id per line, optionally followed by :page.</FieldDescription>
            <FieldError errors={[errors.sources]} />
          </Field>
          <Field data-invalid={!!errors.run_as_group_ids}>
            <FieldLabel>Ask as members of</FieldLabel>
            <Controller
              control={form.control}
              name="run_as_group_ids"
              render={({ field }) => (
                <GroupChecklist groups={groups.data ?? []} value={field.value} onChange={field.onChange} idPrefix="case-group" />
              )}
            />
            <FieldError errors={[errors.run_as_group_ids]} />
          </Field>
          <Field>
            <FieldLabel>Limit to collections (optional)</FieldLabel>
            <Controller
              control={form.control}
              name="collection_ids"
              render={({ field }) => (
                <GroupChecklist
                  groups={(collections.data ?? []).map((c) => ({ id: c.id, name: c.name, description: "" }))}
                  value={field.value}
                  onChange={field.onChange}
                  idPrefix="case-collection"
                  empty="No collections yet."
                />
              )}
            />
          </Field>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              Add case
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
```

`GroupChecklist` is reused for collections, since it only needs `{id, name}`. Its `empty` prop gives the right empty text.

`frontend/app/admin/evaluation/sets/[id]/page.tsx`:

```tsx
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useParams } from "next/navigation"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { CaseDialog } from "@/components/admin/case-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { adminApi } from "@/lib/admin-api"
import { ApiError } from "@/lib/api"
import type { EvalCase, ImportResult } from "@/lib/types"

export default function EvalSetPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  const [imported, setImported] = useState<ImportResult | null>(null)
  const set = useQuery({ queryKey: ["admin", "eval-set", id], queryFn: () => adminApi.evalSet(id) })
  const cases = useQuery({ queryKey: ["admin", "eval-cases", id], queryFn: () => adminApi.evalCases(id) })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "eval-cases", id] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "eval-set", id] })
    void queryClient.invalidateQueries({ queryKey: ["admin", "eval-sets"] })
  }
  const importCsv = useMutation({
    mutationFn: (file: File) => adminApi.importCases(id, file),
    onSuccess: (result) => {
      setImported(result)
      refresh()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Import failed"),
  })
  const remove = useMutation({
    mutationFn: adminApi.deleteCase,
    onSuccess: refresh,
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not delete the case"),
  })

  const columns: ColumnDef<EvalCase>[] = [
    { accessorKey: "question", header: "Question", cell: ({ row }) => <span className="line-clamp-3 max-w-md">{row.original.question}</span> },
    {
      id: "expected",
      header: "Expected",
      cell: ({ row }) =>
        row.original.unanswerable ? (
          <Badge variant="outline">Unanswerable</Badge>
        ) : (
          <span className="line-clamp-3 max-w-sm">{row.original.expected_answer ?? "—"}</span>
        ),
    },
    { id: "sources", header: "Sources", cell: ({ row }) => row.original.expected_sources.length || "—" },
    { accessorKey: "origin", header: "Origin" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(row.original.id)}>
          Delete
        </Button>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title={set.data?.name ?? "Test set"}
        description={set.data?.description || "Questions with expected answers and sources."}
        actions={
          <>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              aria-label="Import CSV"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ""
                if (file) importCsv.mutate(file)
              }}
            />
            <Button variant="outline" disabled={importCsv.isPending} onClick={() => fileInput.current?.click()}>
              Import CSV
            </Button>
            <Button onClick={() => setAdding(true)}>Add case</Button>
          </>
        }
      />
      {imported && (
        <div className="mb-4 rounded-md border p-3 text-sm" role="status">
          <p>{imported.created} cases imported</p>
          {imported.errors.length > 0 && (
            <ul className="mt-1 text-destructive">
              {imported.errors.map((e) => (
                <li key={e.row}>
                  Line {e.row}: {e.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="mb-3 text-xs text-muted-foreground">
        CSV columns: question, expected_answer, expected_sources (doc_id[:page];…), collections
        (names; …), groups (names; …), unanswerable.
      </p>
      <DataTable columns={columns} data={cases.data ?? []} isLoading={cases.isLoading} getRowId={(c) => c.id} empty="No cases yet." />
      <CaseDialog setId={id} open={adding} onOpenChange={setAdding} />
    </>
  )
}
```

In the test, the page heading comes from `PageHeader`'s `<h1>` ("Core"), and the "Add case" name matches both the page button and, later, the dialog's submit button. The test clicks the page button before the dialog opens, then scopes the second click to the dialog.

- [ ] **Step 5: Run detail and compare**

`frontend/app/admin/evaluation/runs/[id]/page.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import type { ColumnDef } from "@tanstack/react-table"
import { useParams } from "next/navigation"

import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { METRIC_LABELS, RunStatusBadge, RunSummary } from "@/components/admin/run-summary"
import { adminApi } from "@/lib/admin-api"
import { traceUrl } from "@/lib/config"
import { formatDateTime, formatUsd } from "@/lib/format"
import type { EvalResult } from "@/lib/types"

const columns: ColumnDef<EvalResult>[] = [
  { accessorKey: "question", header: "Question", cell: ({ row }) => <span className="line-clamp-3 max-w-sm">{row.original.question}</span> },
  { accessorKey: "outcome", header: "Outcome" },
  { id: "answer", header: "Answer", cell: ({ row }) => <span className="line-clamp-3 max-w-md whitespace-pre-wrap">{row.original.error ?? row.original.answer}</span> },
  {
    id: "metrics",
    header: "Metrics",
    cell: ({ row }) => (
      <ul className="text-xs">
        {Object.entries(row.original.metrics)
          .filter(([, v]) => v !== null)
          .map(([k, v]) => (
            <li key={k}>
              {METRIC_LABELS[k] ?? k}: {(v as number).toFixed(2)}
            </li>
          ))}
      </ul>
    ),
  },
  { id: "latency", header: "Latency", cell: ({ row }) => `${row.original.latency_ms} ms` },
  { id: "cost", header: "Cost", cell: ({ row }) => formatUsd(row.original.cost_usd) },
  {
    id: "trace",
    header: "Trace",
    cell: ({ row }) => {
      const url = traceUrl(row.original.trace_id)
      return url ? (
        <a className="underline" href={url} target="_blank" rel="noreferrer">
          Open
        </a>
      ) : (
        "—"
      )
    },
  },
]

export default function EvalRunPage() {
  const { id } = useParams<{ id: string }>()
  const { data, isError } = useQuery({
    queryKey: ["admin", "eval-run", id],
    queryFn: () => adminApi.evalRun(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "queued" || status === "running" ? 5000 : false
    },
  })
  if (isError) return <p className="text-sm text-destructive">Could not load this run.</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <>
      <PageHeader
        title={`Run ${formatDateTime(data.created_at)}`}
        description={`${data.case_count} cases · config ${data.rag_config_version ? `v${data.rag_config_version}` : "defaults"}`}
        actions={<RunStatusBadge status={data.status} />}
      />
      {data.error && <p className="mb-4 text-sm text-destructive">{data.error}</p>}
      {data.status === "completed" && <RunSummary summary={data.summary} />}
      <div className="mt-6">
        <DataTable columns={columns} data={data.results} getRowId={(r) => r.id} empty="No results yet." />
      </div>
    </>
  )
}
```

`frontend/components/admin/compare-view.tsx`:

```tsx
"use client"

import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { METRIC_LABELS } from "@/components/admin/run-summary"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { adminApi } from "@/lib/admin-api"
import { cn } from "@/lib/utils"

// For these, lower is better.
const LOWER_IS_BETTER = new Set(["latency_p95_ms", "cost_per_question_usd"])

export function CompareView({ a, b }: { a: string | undefined; b: string | undefined }) {
  const [onlyRegressions, setOnlyRegressions] = useState(false)
  const { data, isError } = useQuery({
    queryKey: ["admin", "compare", a, b],
    queryFn: () => adminApi.compareRuns(a!, b!),
    enabled: !!a && !!b,
  })
  if (!a || !b) return <p className="text-sm text-muted-foreground">Pick two runs to compare on the Runs tab.</p>
  if (isError) return <p className="text-sm text-destructive">Could not compare these runs.</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>
  const questions = data.questions.filter((q) => !onlyRegressions || q.regressed)
  return (
    <div className="grid gap-6">
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Metric</TableHead>
              <TableHead>Change (B − A)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(data.deltas).map(([key, delta]) => {
              const worse = LOWER_IS_BETTER.has(key) ? delta > 0 : delta < 0
              return (
                <TableRow key={key}>
                  <TableCell>{METRIC_LABELS[key] ?? key}</TableCell>
                  <TableCell className={cn("tabular-nums", worse && "text-destructive")}>
                    {delta > 0 ? "+" : ""}
                    {delta.toFixed(Math.abs(delta) < 0.01 && delta !== 0 ? 4 : 2)}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center gap-2">
        <Switch id="only-regressions" checked={onlyRegressions} onCheckedChange={setOnlyRegressions} />
        <Label htmlFor="only-regressions">Only regressions</Label>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted">
            <TableRow>
              <TableHead>Question</TableHead>
              <TableHead>A</TableHead>
              <TableHead>B</TableHead>
              <TableHead>Regression</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {questions.map((q) => (
              <TableRow key={q.case_id} className={q.regressed ? "bg-destructive/5" : undefined}>
                <TableCell className="max-w-xs align-top">{q.question}</TableCell>
                <TableCell className="max-w-sm align-top">
                  <Badge variant="outline">{q.a.outcome}</Badge>
                  <p className="mt-1 line-clamp-4 text-xs whitespace-pre-wrap">{q.a.answer}</p>
                </TableCell>
                <TableCell className="max-w-sm align-top">
                  <Badge variant="outline">{q.b.outcome}</Badge>
                  <p className="mt-1 line-clamp-4 text-xs whitespace-pre-wrap">{q.b.answer}</p>
                </TableCell>
                <TableCell className="align-top">
                  {q.reasons.map((r) => (
                    <p key={r} className="text-destructive">
                      {r}
                    </p>
                  ))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
```

The test expects the score delta `-0.2` to render as `-0.20`: `delta > 0` is false, so there's no "+", and `toFixed(2)` gives `-0.20`.

`frontend/app/admin/evaluation/compare/page.tsx` (a server component: Next 16 passes `searchParams` as a Promise):

```tsx
import { PageHeader } from "@/components/admin/page-header"
import { CompareView } from "@/components/admin/compare-view"

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ a?: string; b?: string }>
}) {
  const { a, b } = await searchParams
  return (
    <>
      <PageHeader title="Compare runs" description="Per-question changes from A (baseline) to B." />
      <CompareView a={a} b={b} />
    </>
  )
}
```

- [ ] **Step 6: Run the tests and checks**

Run: `npm test -- app/admin components/admin && npm run lint && npm run typecheck && npm run build`
Expected: PASS. The build confirms the server compare page and the client `[id]` pages.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/admin/evaluation frontend/components/admin/case-dialog.tsx frontend/components/admin/compare-view.tsx frontend/components/admin/compare-view.test.tsx frontend/components/admin/run-summary.tsx
git commit -m "feat(admin): evaluation sets, cases, csv import, runs, run detail and comparison"
```

---

### Task 10: Models & RAG config, Guardrails (super_admin)

**Files:**
- Create: `frontend/lib/config-version.ts`, `frontend/components/admin/activate-dialog.tsx`
- Create: `frontend/app/admin/models/page.tsx`, `frontend/app/admin/guardrails/page.tsx`
- Test: `frontend/app/admin/models/page.test.tsx`, `frontend/app/admin/guardrails/page.test.tsx`

**Interfaces:**
- Consumes:
  - `adminApi`: `ragConfigs`, `activeConfig`, `createConfig`, `activateConfig`;
  - `SuperAdminOnly`, `PasswordDialog`, `DataTable`, `PageHeader`, `formatPercent`, `formatDateTime`;
  - the types `RagConfig`, `RagConfigVersion`, `GuardrailSettings`, `MODERATION_CATEGORIES` and `RERANKER_MODELS`.
- Produces:
  - `useActiveConfig()`, `useConfigVersions()` and `useCreateVersion()` (which returns a mutation of `{config, note}` → `RagConfigVersion`) in `lib/config-version.ts`;
  - `ActivateDialog({target, versions, onOpenChange})`;
  - the `/admin/models` and `/admin/guardrails` pages.
- Query keys: `["admin","rag-configs"]` and `["admin","rag-configs","active"]`. Invalidating `["admin","rag-configs"]` refreshes both.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/models/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import ModelsPage from "@/app/admin/models/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const guardrails = { groundedness_check: true, pii_patterns: [] }
const config = {
  chat_model: "gpt-5-mini",
  rewrite_model: "gpt-5-nano",
  fallback_model: null,
  eval_judge_model: "gpt-5-mini",
  reranker_model: "Xenova/ms-marco-MiniLM-L-12-v2",
  search_top_k: 50,
  rerank_top_n: 8,
  rerank_threshold: 0.1,
  history_turns: 3,
  system_prompt: "Answer from sources.",
  rewrite_prompt: "Rewrite.",
  not_found_message: "Not found.",
  prices: { "gpt-5-mini": { input_per_mtok: 0.25, output_per_mtok: 2 } },
  guardrails,
}
const v1 = { id: "id1", version: 1, note: "first", is_active: false, created_at: "2026-10-01T00:00:00Z", activated_at: null, latest_eval: { run_id: "r1", eval_set_id: "s1", score: 0.82, finished_at: null }, config }
const v2 = { ...v1, id: "id2", version: 2, note: "second", is_active: true, latest_eval: { run_id: "r2", eval_set_id: "s1", score: 0.9, finished_at: null } }

function mockApi(role: string) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (url === "/api/auth/me")
      return jsonResponse({ id: "u1", username: "r", full_name: "R", role, is_active: true, must_change_password: false, groups: [] })
    if (url === "/api/admin/rag-configs/active") return jsonResponse({ version: 2, config, latest_eval: v2.latest_eval })
    if (init?.method === "POST") return jsonResponse({ ...v2, id: "id3", version: 3, is_active: false }, 201)
    return jsonResponse([v2, v1])
  })
}

const posted = (fetchMock: ReturnType<typeof mockApi>, url: string) => {
  const call = fetchMock.mock.calls.find(([u, i]) => String(u) === url && i?.method === "POST")
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("ModelsPage", () => {
  it("is closed to admins", async () => {
    const fetchMock = mockApi("admin")
    renderWithProviders(<ModelsPage />)
    expect(await screen.findByText("Only super admins can open this page.")).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/admin/rag-configs"))).toBe(false)
  })

  it("saves a new version from the active config", async () => {
    const fetchMock = mockApi("super_admin")
    renderWithProviders(<ModelsPage />)
    const chat = await screen.findByLabelText("Chat model")
    await userEvent.clear(chat)
    await userEvent.type(chat, "gpt-5")
    await userEvent.type(screen.getByLabelText("Note"), "bigger model")
    await userEvent.click(screen.getByRole("button", { name: "Save as new version" }))
    await waitFor(() => expect(posted(fetchMock, "/api/admin/rag-configs")).toBeDefined())
    const body = posted(fetchMock, "/api/admin/rag-configs")
    expect(body.note).toBe("bigger model")
    expect(body.config.chat_model).toBe("gpt-5")
    expect(body.config.guardrails).toEqual(guardrails) // untouched
    expect(body.config.fallback_model).toBeNull()
  })

  it("rolls back with the eval warning and a password", async () => {
    const fetchMock = mockApi("super_admin")
    renderWithProviders(<ModelsPage />)
    await userEvent.click(await screen.findByRole("button", { name: "Activate v1" }))
    expect(await screen.findByText(/v1 scored 82%.*active v2 scored 90%/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Your password"), "pw-123")
    await userEvent.click(screen.getByRole("button", { name: "Activate" }))
    await waitFor(() =>
      expect(posted(fetchMock, "/api/admin/rag-configs/id1/activate")).toEqual({ password: "pw-123" })
    )
  })
})
```

`frontend/app/admin/guardrails/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import GuardrailsPage from "@/app/admin/guardrails/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const guardrails = {
  rate_limit_per_minute: 10,
  max_question_chars: 2000,
  moderation: { violence: "block", hate: "block", harassment: "block", sexual: "block", illegal: "block", weapons: "block", self_harm: "flag" },
  self_harm_support: true,
  injection_check: true,
  exfiltration_check: true,
  scope_check: false,
  scope_description: "",
  classifier_model: "gpt-5-nano",
  blocked_message: "I can't help with that request.",
  off_topic_message: "I can only help with company documents.",
  support_message: "Please reach out.",
  pii_redaction: true,
  pii_patterns: [{ name: "employee_number", regex: "\\bEMP-\\d{6}\\b" }],
  system_prompt_leak_check: true,
  groundedness_check: true,
  judge_model: "gpt-5-nano",
  strike_limit: 3,
  strike_window_hours: 24,
  strike_lock_hours: 24,
  user_daily_cost_usd: 2,
  installation_daily_cost_usd: 50,
  cost_alert_ratio: 0.8,
}
const config = { chat_model: "gpt-5-mini", guardrails }

describe("GuardrailsPage", () => {
  it("saves guardrail changes as a new version and offers activation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input)
      if (url === "/api/auth/me")
        return jsonResponse({ id: "u1", username: "r", full_name: "R", role: "super_admin", is_active: true, must_change_password: false, groups: [] })
      if (url === "/api/admin/rag-configs/active") return jsonResponse({ version: 4, config, latest_eval: null })
      if (init?.method === "POST")
        return jsonResponse({ id: "id5", version: 5, note: "", is_active: false, created_at: "", activated_at: null, latest_eval: null, config }, 201)
      return jsonResponse([])
    })
    renderWithProviders(<GuardrailsPage />)
    await userEvent.click(await screen.findByLabelText("Groundedness check"))
    await userEvent.selectOptions(screen.getByLabelText("Weapons"), "flag")
    await userEvent.click(screen.getByRole("button", { name: "Add pattern" }))
    await userEvent.type(screen.getByLabelText("Pattern 2 name"), "badge_id")
    await userEvent.type(screen.getByLabelText("Pattern 2 regex"), "B-[[0-9]{{4}")
    await userEvent.click(screen.getByRole("button", { name: "Save as new version" }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u) === "/api/admin/rag-configs" && i?.method === "POST")
      const body = JSON.parse(String(call?.[1]?.body))
      expect(body.config.chat_model).toBe("gpt-5-mini")
      expect(body.config.guardrails.groundedness_check).toBe(false)
      expect(body.config.guardrails.moderation.weapons).toBe("flag")
      expect(body.config.guardrails.pii_patterns[1]).toEqual({ name: "badge_id", regex: "B-[0-9]{4}" })
    })
    expect(await screen.findByRole("button", { name: "Activate v5" })).toBeInTheDocument()
  })
})
```

`userEvent.type` treats `{` and `[` as the start of key descriptors, so `{{` and `[[` type a literal `{` and `[`.

Run: `npm test -- app/admin/models app/admin/guardrails`
Expected: FAIL.

- [ ] **Step 2: Version hooks and the activate dialog**

`frontend/lib/config-version.ts`:

```ts
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { adminApi } from "@/lib/admin-api"
import type { RagConfig } from "@/lib/types"

export const useActiveConfig = () =>
  useQuery({ queryKey: ["admin", "rag-configs", "active"], queryFn: adminApi.activeConfig })

export const useConfigVersions = () =>
  useQuery({ queryKey: ["admin", "rag-configs"], queryFn: adminApi.ragConfigs })

/** Saves a new (inactive) version; activation is a separate, password-confirmed step. */
export function useCreateVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ config, note }: { config: RagConfig; note: string }) =>
      adminApi.createConfig(config, note),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "rag-configs"] }),
  })
}
```

`frontend/components/admin/activate-dialog.tsx`:

```tsx
"use client"

import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { PasswordDialog } from "@/components/admin/password-dialog"
import { adminApi } from "@/lib/admin-api"
import { formatPercent } from "@/lib/format"
import type { RagConfigVersion } from "@/lib/types"

const scoreText = (v: RagConfigVersion | undefined) =>
  v?.latest_eval ? formatPercent(v.latest_eval.score) : "no eval yet"

/** Activation (or rollback) with the spec §7.1 warning: latest eval score vs the active one. */
export function ActivateDialog({
  target,
  versions,
  onOpenChange,
}: {
  target: RagConfigVersion | null
  versions: RagConfigVersion[]
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const active = versions.find((v) => v.is_active)
  const differentSets =
    !!target?.latest_eval &&
    !!active?.latest_eval &&
    target.latest_eval.eval_set_id !== active.latest_eval.eval_set_id
  const comparison = target
    ? active
      ? `v${target.version} scored ${scoreText(target)}; the active v${active.version} scored ${scoreText(active)}${differentSets ? " (on a different test set)" : ""}.`
      : `v${target.version} scored ${scoreText(target)}; no version is active yet.`
    : ""
  return (
    <PasswordDialog
      open={!!target}
      onOpenChange={onOpenChange}
      title={`Activate v${target?.version ?? ""}?`}
      description={`${comparison} Every new answer will use this configuration.`}
      confirmLabel="Activate"
      onConfirm={async (password) => {
        await adminApi.activateConfig(target!.id, password)
        await queryClient.invalidateQueries({ queryKey: ["admin", "rag-configs"] })
        toast.success(`v${target!.version} is now active`)
      }}
    />
  )
}
```

The test regex `/v1 scored 82%.*active v2 scored 90%/` matches "v1 scored 82%; the active v2 scored 90%."

- [ ] **Step 3: The models page**

`frontend/app/admin/models/page.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import type { ColumnDef } from "@tanstack/react-table"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ActivateDialog } from "@/components/admin/activate-dialog"
import { DataTable } from "@/components/admin/data-table"
import { PageHeader } from "@/components/admin/page-header"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { useActiveConfig, useConfigVersions, useCreateVersion } from "@/lib/config-version"
import { formatDateTime, formatPercent } from "@/lib/format"
import { RERANKER_MODELS, type RagConfig, type RagConfigVersion } from "@/lib/types"

const PRICE_HINT = 'JSON like {"gpt-5-mini": {"input_per_mtok": 0.25, "output_per_mtok": 2}}'

function parsePrices(text: string): RagConfig["prices"] | null {
  try {
    const value = JSON.parse(text)
    if (!value || typeof value !== "object" || Array.isArray(value)) return null
    for (const price of Object.values(value)) {
      const p = price as Record<string, unknown>
      if (typeof p?.input_per_mtok !== "number" || typeof p?.output_per_mtok !== "number") return null
    }
    return value
  } catch {
    return null
  }
}

const model = z.string().trim().min(1, "Enter a model name").max(100)
const schema = z.object({
  chat_model: model,
  rewrite_model: model,
  fallback_model: z.string().trim().max(100),
  eval_judge_model: model,
  reranker_model: z.enum(RERANKER_MODELS),
  search_top_k: z.number().int().min(1).max(200),
  rerank_top_n: z.number().int().min(1).max(30),
  rerank_threshold: z.number().min(0).max(1),
  history_turns: z.number().int().min(0).max(20),
  system_prompt: z.string().min(1).max(8000),
  rewrite_prompt: z.string().min(1).max(4000),
  not_found_message: z.string().min(1).max(500),
  prices: z.string().refine((v) => parsePrices(v) !== null, PRICE_HINT),
  note: z.string().max(500),
})
type Values = z.infer<typeof schema>

const toValues = (c: RagConfig): Values => ({
  chat_model: c.chat_model,
  rewrite_model: c.rewrite_model,
  fallback_model: c.fallback_model ?? "",
  eval_judge_model: c.eval_judge_model,
  reranker_model: c.reranker_model,
  search_top_k: c.search_top_k,
  rerank_top_n: c.rerank_top_n,
  rerank_threshold: c.rerank_threshold,
  history_turns: c.history_turns,
  system_prompt: c.system_prompt,
  rewrite_prompt: c.rewrite_prompt,
  not_found_message: c.not_found_message,
  prices: JSON.stringify(c.prices, null, 2),
  note: "",
})

const TEXT_FIELDS = [
  ["chat_model", "Chat model"],
  ["rewrite_model", "Rewrite model"],
  ["fallback_model", "Fallback model (optional)"],
  ["eval_judge_model", "Eval judge model"],
] as const
const NUMBER_FIELDS = [
  ["search_top_k", "Search top k", "1"],
  ["rerank_top_n", "Sources per answer", "1"],
  ["rerank_threshold", "Rerank threshold (0–1)", "0.01"],
  ["history_turns", "History turns", "1"],
] as const
const PROMPT_FIELDS = [
  ["system_prompt", "System prompt", 8],
  ["rewrite_prompt", "Rewrite prompt", 3],
  ["not_found_message", "“Not found” message", 2],
] as const

function ModelsEditor() {
  const active = useActiveConfig()
  const versions = useConfigVersions()
  const create = useCreateVersion()
  const [target, setTarget] = useState<RagConfigVersion | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { errors } = form.formState

  useEffect(() => {
    if (active.data) form.reset(toValues(active.data.config))
  }, [active.data, form])

  async function onSubmit(values: Values) {
    if (!active.data) return
    setFormError(null)
    const { note, prices, fallback_model, ...rest } = values
    const config: RagConfig = {
      ...active.data.config,
      ...rest,
      fallback_model: fallback_model || null,
      prices: parsePrices(prices)!,
    }
    try {
      const saved = await create.mutateAsync({ config, note })
      toast.success(`Saved as v${saved.version}. Activate it to use it.`)
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Could not save. Try again.")
    }
  }

  const columns: ColumnDef<RagConfigVersion>[] = [
    {
      id: "version",
      header: "Version",
      cell: ({ row }) => (
        <span className="flex items-center gap-2">
          v{row.original.version}
          {row.original.is_active && <Badge>Active</Badge>}
        </span>
      ),
    },
    { accessorKey: "note", header: "Note" },
    { id: "created", header: "Created", cell: ({ row }) => formatDateTime(row.original.created_at) },
    {
      id: "eval",
      header: "Latest eval",
      cell: ({ row }) =>
        row.original.latest_eval ? formatPercent(row.original.latest_eval.score) : "—",
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        row.original.is_active ? null : (
          <Button size="sm" variant="outline" aria-label={`Activate v${row.original.version}`} onClick={() => setTarget(row.original)}>
            {(active.data?.version ?? 0) > row.original.version ? "Roll back" : "Activate"}
          </Button>
        ),
    },
  ]

  return (
    <div className="grid gap-6">
      <DataTable columns={columns} data={versions.data ?? []} isLoading={versions.isLoading} getRowId={(v) => v.id} empty="No versions yet; the defaults are in use." />
      <Card>
        <CardHeader>
          <CardTitle>New version</CardTitle>
        </CardHeader>
        <CardContent>
          {active.data && (
            <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)}>
              <div className="grid gap-4 md:grid-cols-2">
                {TEXT_FIELDS.map(([name, label]) => (
                  <Field key={name} data-invalid={!!errors[name]}>
                    <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                    <Input id={`cfg-${name}`} {...form.register(name)} />
                    <FieldError errors={[errors[name]]} />
                  </Field>
                ))}
                <Field>
                  <FieldLabel htmlFor="cfg-reranker">Reranker</FieldLabel>
                  <NativeSelect id="cfg-reranker" {...form.register("reranker_model")}>
                    {RERANKER_MODELS.map((m) => (
                      <NativeSelectOption key={m} value={m}>
                        {m}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </Field>
                {NUMBER_FIELDS.map(([name, label, step]) => (
                  <Field key={name} data-invalid={!!errors[name]}>
                    <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                    <Input id={`cfg-${name}`} type="number" step={step} {...form.register(name, { valueAsNumber: true })} />
                    <FieldError errors={[errors[name]]} />
                  </Field>
                ))}
              </div>
              {PROMPT_FIELDS.map(([name, label, rows]) => (
                <Field key={name} data-invalid={!!errors[name]}>
                  <FieldLabel htmlFor={`cfg-${name}`}>{label}</FieldLabel>
                  <Textarea id={`cfg-${name}`} rows={rows} {...form.register(name)} />
                  <FieldError errors={[errors[name]]} />
                </Field>
              ))}
              <Field data-invalid={!!errors.prices}>
                <FieldLabel htmlFor="cfg-prices">Prices (USD per million tokens)</FieldLabel>
                <Textarea id="cfg-prices" rows={6} className="font-mono text-xs" {...form.register("prices")} />
                <FieldDescription>Every model used must have a price while cost caps are on.</FieldDescription>
                <FieldError errors={[errors.prices]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="cfg-note">Note</FieldLabel>
                <Input id="cfg-note" {...form.register("note")} />
              </Field>
              {formError && (
                <p role="alert" className="text-sm text-destructive">
                  {formError}
                </p>
              )}
              <div>
                <Button type="submit" disabled={create.isPending}>
                  Save as new version
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
      <ActivateDialog target={target} versions={versions.data ?? []} onOpenChange={(open) => !open && setTarget(null)} />
    </div>
  )
}

export default function ModelsPage() {
  return (
    <>
      <PageHeader
        title="Models & RAG config"
        description="Every change is a new version. Compare eval scores, then activate or roll back."
      />
      <SuperAdminOnly>
        <ModelsEditor />
      </SuperAdminOnly>
    </>
  )
}
```

The test clicks `Activate v1` by its aria-label. v1 is older than the active v2, so the button's visible text is "Roll back", while the aria-label stays `Activate v1`. That's intended: one accessible name, whatever the direction.

- [ ] **Step 4: The guardrails page**

`frontend/app/admin/guardrails/page.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect, useState } from "react"
import { Controller, useFieldArray, useForm, type Control } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { ActivateDialog } from "@/components/admin/activate-dialog"
import { PageHeader } from "@/components/admin/page-header"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { useActiveConfig, useConfigVersions, useCreateVersion } from "@/lib/config-version"
import { MODERATION_CATEGORIES, type GuardrailSettings, type RagConfigVersion } from "@/lib/types"

const action = z.enum(["block", "flag", "off"])
const schema = z.object({
  rate_limit_per_minute: z.number().int().min(1).max(600),
  max_question_chars: z.number().int().min(10).max(4000),
  moderation: z.object(Object.fromEntries(MODERATION_CATEGORIES.map((c) => [c, action])) as Record<
    (typeof MODERATION_CATEGORIES)[number],
    typeof action
  >),
  self_harm_support: z.boolean(),
  injection_check: z.boolean(),
  exfiltration_check: z.boolean(),
  scope_check: z.boolean(),
  scope_description: z.string().max(1000),
  classifier_model: z.string().trim().min(1).max(100),
  blocked_message: z.string().min(1).max(1000),
  off_topic_message: z.string().min(1).max(1000),
  support_message: z.string().min(1).max(2000),
  pii_redaction: z.boolean(),
  pii_patterns: z
    .array(
      z.object({
        name: z.string().regex(/^[a-z0-9_]+$/, "Lowercase letters, digits and _").max(50),
        regex: z.string().min(1).max(300),
      })
    )
    .max(20),
  system_prompt_leak_check: z.boolean(),
  groundedness_check: z.boolean(),
  judge_model: z.string().trim().min(1).max(100),
  strike_limit: z.number().int().min(1).max(20),
  strike_window_hours: z.number().int().min(1).max(720),
  strike_lock_hours: z.number().int().min(1).max(720),
  user_daily_cost_usd: z.number().min(0),
  installation_daily_cost_usd: z.number().min(0),
  cost_alert_ratio: z.number().gt(0).max(1),
})
type Values = z.infer<typeof schema>
type BoolKey = { [K in keyof Values]: Values[K] extends boolean ? K : never }[keyof Values]
type NumberKey = { [K in keyof Values]: Values[K] extends number ? K : never }[keyof Values]
type TextKey = Extract<keyof Values, "scope_description" | "classifier_model" | "judge_model" | "blocked_message" | "off_topic_message" | "support_message">

const CATEGORY_LABELS: Record<string, string> = {
  violence: "Violence",
  hate: "Hate",
  harassment: "Harassment",
  sexual: "Sexual",
  illegal: "Illegal activity",
  weapons: "Weapons",
  self_harm: "Self-harm",
}

function Toggle({ control, name, label }: { control: Control<Values>; name: BoolKey; label: string }) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <div className="flex items-center gap-2">
          <Switch id={`gr-${name}`} checked={field.value} onCheckedChange={field.onChange} />
          <Label htmlFor={`gr-${name}`}>{label}</Label>
        </div>
      )}
    />
  )
}

function GuardrailsEditor() {
  const active = useActiveConfig()
  const versions = useConfigVersions()
  const create = useCreateVersion()
  const [note, setNote] = useState("")
  const [saved, setSaved] = useState<RagConfigVersion | null>(null)
  const [activating, setActivating] = useState<RagConfigVersion | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const { register, control, formState } = form
  const patterns = useFieldArray({ control, name: "pii_patterns" })

  useEffect(() => {
    if (active.data) form.reset(active.data.config.guardrails)
  }, [active.data, form])

  async function onSubmit(values: Values) {
    if (!active.data) return
    setFormError(null)
    try {
      const version = await create.mutateAsync({
        config: { ...active.data.config, guardrails: values as GuardrailSettings },
        note: note || "Guardrail settings",
      })
      setSaved(version)
      toast.success(`Saved as v${version.version}. Activate it to use it.`)
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Could not save. Try again.")
    }
  }

  const number = (name: NumberKey, label: string, step = "1") => (
    <Field data-invalid={!!formState.errors[name]}>
      <FieldLabel htmlFor={`gr-${name}`}>{label}</FieldLabel>
      <Input id={`gr-${name}`} type="number" step={step} {...register(name, { valueAsNumber: true })} />
      <FieldError errors={[formState.errors[name]]} />
    </Field>
  )
  const text = (name: TextKey, label: string, rows = 0) => (
    <Field data-invalid={!!formState.errors[name]}>
      <FieldLabel htmlFor={`gr-${name}`}>{label}</FieldLabel>
      {rows ? <Textarea id={`gr-${name}`} rows={rows} {...register(name)} /> : <Input id={`gr-${name}`} {...register(name)} />}
      <FieldError errors={[formState.errors[name]]} />
    </Field>
  )

  if (!active.data) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <>
    <form className="grid gap-4" onSubmit={form.handleSubmit(onSubmit)}>
      <Card>
        <CardHeader>
          <CardTitle>Input checks</CardTitle>
          <CardDescription>Run before retrieval; blocked questions never reach the model.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {number("rate_limit_per_minute", "Questions per minute per user")}
          {number("max_question_chars", "Max question length (characters)")}
          <Toggle control={control} name="injection_check" label="Prompt-injection check" />
          <Toggle control={control} name="exfiltration_check" label="Exfiltration check (sensitive collections)" />
          <Toggle control={control} name="scope_check" label="Scope check" />
          {text("classifier_model", "Classifier model")}
          <div className="md:col-span-2">{text("scope_description", "In-scope topics", 2)}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Content moderation</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          {MODERATION_CATEGORIES.map((category) => (
            <Field key={category}>
              <FieldLabel htmlFor={`gr-mod-${category}`}>{CATEGORY_LABELS[category]}</FieldLabel>
              <NativeSelect id={`gr-mod-${category}`} {...register(`moderation.${category}`)}>
                <NativeSelectOption value="block">Block</NativeSelectOption>
                <NativeSelectOption value="flag">Flag for review</NativeSelectOption>
                <NativeSelectOption value="off">Off</NativeSelectOption>
              </NativeSelect>
            </Field>
          ))}
          <div className="md:col-span-3">
            <Toggle control={control} name="self_harm_support" label="Answer self-harm messages with support resources" />
          </div>
          <div className="md:col-span-3">{text("support_message", "Support message", 3)}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Output checks</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Toggle control={control} name="pii_redaction" label="PII redaction" />
            <Toggle control={control} name="system_prompt_leak_check" label="System-prompt leak check" />
            <Toggle control={control} name="groundedness_check" label="Groundedness check" />
            {text("judge_model", "Judge model")}
          </div>
          <div className="grid gap-2">
            <Label>Company identifiers to redact</Label>
            {patterns.fields.map((field, index) => (
              <div key={field.id} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
                <Input aria-label={`Pattern ${index + 1} name`} placeholder="employee_number" {...register(`pii_patterns.${index}.name`)} />
                <Input aria-label={`Pattern ${index + 1} regex`} className="font-mono" placeholder="\bEMP-\d{6}\b" {...register(`pii_patterns.${index}.regex`)} />
                <Button type="button" variant="ghost" onClick={() => patterns.remove(index)}>
                  Remove
                </Button>
                <FieldError className="md:col-span-3" errors={[formState.errors.pii_patterns?.[index]?.name, formState.errors.pii_patterns?.[index]?.regex]} />
              </div>
            ))}
            <div>
              <Button type="button" variant="outline" size="sm" onClick={() => patterns.append({ name: "", regex: "" })}>
                Add pattern
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Accounts and cost</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          {number("strike_limit", "Strikes before a lock")}
          {number("strike_window_hours", "Strike window (hours)")}
          {number("strike_lock_hours", "Lock length (hours)")}
          {number("user_daily_cost_usd", "Daily cost cap per user (USD, 0 = off)", "0.01")}
          {number("installation_daily_cost_usd", "Daily cost cap, whole installation (USD, 0 = off)", "0.01")}
          {number("cost_alert_ratio", "Alert at this share of a cap (0–1)", "0.05")}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Messages</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {text("blocked_message", "Blocked message", 2)}
          {text("off_topic_message", "Off-topic message", 2)}
        </CardContent>
      </Card>
      <Field>
        <FieldLabel htmlFor="gr-note">Note</FieldLabel>
        <Input id="gr-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {formError && (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={create.isPending}>
          Save as new version
        </Button>
        {saved && (
          <Button type="button" variant="outline" onClick={() => setActivating(saved)}>
            Activate v{saved.version}
          </Button>
        )}
      </div>
    </form>
    {/* Outside the form: React portals still bubble submit events to ancestors. */}
    <ActivateDialog
      target={activating}
      versions={versions.data ?? []}
      onOpenChange={(open) => {
        if (!open) setActivating(null)
      }}
    />
    </>
  )
}

export default function GuardrailsPage() {
  return (
    <>
      <PageHeader
        title="Guardrails"
        description="Checks on questions and answers. Changes are saved as a new RAG config version."
      />
      <SuperAdminOnly>
        <GuardrailsEditor />
      </SuperAdminOnly>
    </>
  )
}
```

Run `npm run format` afterwards; it also re-indents the fragment.

- [ ] **Step 5: Run the tests and checks**

Run: `npm test -- app/admin && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/config-version.ts frontend/components/admin/activate-dialog.tsx frontend/app/admin/models frontend/app/admin/guardrails
git commit -m "feat(admin): models & rag config and guardrails editors with eval-aware activation"
```

---

### Task 11: Settings — branding, logo, OpenAI key (super_admin)

**Files:**
- Create: `frontend/app/admin/settings/page.tsx`
- Test: `frontend/app/admin/settings/page.test.tsx`

**Interfaces:**
- Consumes: `adminApi.updateBranding`, `uploadLogo`, `removeLogo`, `openaiKey`, `setOpenaiKey` and `clearOpenaiKey`; `api.branding`; `useBranding`; `SuperAdminOnly`; `PasswordDialog`; `formatDateTime`; the types `Branding` and `KeyStatus`.
- Produces: the `/admin/settings` page. Saving branding writes the response into the `["branding"]` query, so the name, color and logo change at once everywhere.

- [ ] **Step 1: Write the failing tests**

`frontend/app/admin/settings/page.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import SettingsPage from "@/app/admin/settings/page"
import { jsonResponse, renderWithProviders } from "@/test/render"

const KEY = "sk-live-abcdefghijklmnop9876"
const branding = { app_name: "Knowledge Assistant", primary_color: null, logo_url: null }

function mockApi(status: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input)
    if (url === "/api/auth/me")
      return jsonResponse({ id: "u1", username: "r", full_name: "R", role: "super_admin", is_active: true, must_change_password: false, groups: [] })
    if (url === "/api/branding") return jsonResponse(branding)
    if (url === "/api/admin/settings/branding")
      return jsonResponse({ ...branding, ...JSON.parse(String(init?.body)) })
    if (url === "/api/admin/settings/openai-key" && init?.method === "PUT")
      return jsonResponse({ source: "database", last4: "9876", updated_at: "2026-10-08T10:00:00Z", secrets_key_configured: true })
    return jsonResponse(status)
  })
}

const sent = (fetchMock: ReturnType<typeof mockApi>, method: string, url: string) => {
  const call = fetchMock.mock.calls.find(([u, i]) => String(u) === url && i?.method === method)
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

describe("SettingsPage", () => {
  it("validates and saves branding", async () => {
    const fetchMock = mockApi({ source: "none", last4: null, updated_at: null, secrets_key_configured: true })
    renderWithProviders(<SettingsPage />)
    const name = await screen.findByLabelText("App name")
    await userEvent.clear(name)
    await userEvent.type(name, "Acme Docs")
    await userEvent.type(screen.getByLabelText("Primary color"), "blue")
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }))
    expect(await screen.findByText("Use a hex color like #1d4ed8")).toBeInTheDocument()
    expect(sent(fetchMock, "PUT", "/api/admin/settings/branding")).toBeUndefined()

    await userEvent.clear(screen.getByLabelText("Primary color"))
    await userEvent.type(screen.getByLabelText("Primary color"), "#1d4ed8")
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }))
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", "/api/admin/settings/branding")).toEqual({
        app_name: "Acme Docs",
        primary_color: "#1d4ed8",
      })
    )
  })

  it("saves the key after a password and never shows it again", async () => {
    const fetchMock = mockApi({ source: "environment", last4: "1234", updated_at: null, secrets_key_configured: true })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText(/RAG_OPENAI_API_KEY/)).toBeInTheDocument()
    const input = screen.getByLabelText("New OpenAI API key")
    await userEvent.type(input, KEY)
    await userEvent.click(screen.getByRole("button", { name: "Save key" }))
    await userEvent.type(await screen.findByLabelText("Your password"), "pw-123")
    await userEvent.click(screen.getByRole("button", { name: "Save key securely" }))
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", "/api/admin/settings/openai-key")).toEqual({ api_key: KEY, password: "pw-123" })
    )
    expect(await screen.findByText(/…9876/)).toBeInTheDocument()
    expect(input).toHaveValue("")
    expect(document.body.textContent).not.toContain(KEY)
  })

  it("explains when RAG_SECRETS_KEY is missing", async () => {
    mockApi({ source: "environment", last4: "1234", updated_at: null, secrets_key_configured: false })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText(/Set RAG_SECRETS_KEY/)).toBeInTheDocument()
    expect(screen.getByLabelText("New OpenAI API key")).toBeDisabled()
  })
})
```

Run: `npm test -- app/admin/settings`
Expected: FAIL.

- [ ] **Step 2: Write the page**

`frontend/app/admin/settings/page.tsx`:

```tsx
"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { PageHeader } from "@/components/admin/page-header"
import { PasswordDialog } from "@/components/admin/password-dialog"
import { SuperAdminOnly } from "@/components/admin/super-admin-only"
import { BrandMark } from "@/components/branding"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { adminApi } from "@/lib/admin-api"
import { api, ApiError } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { Branding, KeyStatus } from "@/lib/types"

const errorText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.")

const brandingSchema = z.object({
  app_name: z.string().trim().min(1, "Enter a name").max(60),
  primary_color: z
    .string()
    .trim()
    .refine((v) => v === "" || /^#[0-9a-fA-F]{6}$/.test(v), "Use a hex color like #1d4ed8"),
})

function BrandingCard() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const { data: branding } = useQuery({ queryKey: ["branding"], queryFn: api.branding })
  const form = useForm<z.infer<typeof brandingSchema>>({ resolver: zodResolver(brandingSchema) })
  useEffect(() => {
    if (branding) form.reset({ app_name: branding.app_name, primary_color: branding.primary_color ?? "" })
  }, [branding, form])
  const apply = (next: Branding) => queryClient.setQueryData(["branding"], next)
  const save = useMutation({
    mutationFn: adminApi.updateBranding,
    onSuccess: (next) => {
      apply(next)
      toast.success("Branding saved")
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const upload = useMutation({
    mutationFn: adminApi.uploadLogo,
    onSuccess: (next) => {
      apply(next)
      toast.success("Logo updated")
    },
    onError: (e) => toast.error(errorText(e)),
  })
  const remove = useMutation({
    mutationFn: adminApi.removeLogo,
    onSuccess: apply,
    onError: (e) => toast.error(errorText(e)),
  })
  const { errors } = form.formState
  if (!branding) return null // the form fills from saved branding; typing earlier would be lost
  return (
    <Card>
      <CardHeader>
        <CardTitle>Branding</CardTitle>
        <CardDescription>Shown on the sign-in page, in both sidebars and the browser tab.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={form.handleSubmit((v) =>
            save.mutate({ app_name: v.app_name, primary_color: v.primary_color || null })
          )}
        >
          <Field data-invalid={!!errors.app_name}>
            <FieldLabel htmlFor="brand-name">App name</FieldLabel>
            <Input id="brand-name" {...form.register("app_name")} />
            <FieldError errors={[errors.app_name]} />
          </Field>
          <Field data-invalid={!!errors.primary_color}>
            <FieldLabel htmlFor="brand-color">Primary color</FieldLabel>
            <Input id="brand-color" placeholder="#1d4ed8 (empty = default)" {...form.register("primary_color")} />
            <FieldError errors={[errors.primary_color]} />
          </Field>
          <div className="md:col-span-2">
            <Button type="submit" disabled={save.isPending}>
              Save branding
            </Button>
          </div>
        </form>
        <div className="flex flex-wrap items-center gap-3">
          <BrandMark className="size-12" />
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label="Logo file"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file) upload.mutate(file)
            }}
          />
          <Button variant="outline" disabled={upload.isPending} onClick={() => fileInput.current?.click()}>
            Upload logo
          </Button>
          {branding?.logo_url && (
            <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
              Remove logo
            </Button>
          )}
          <FieldDescription>PNG, JPEG or WebP, at most 512 KB.</FieldDescription>
        </div>
      </CardContent>
    </Card>
  )
}

function keyDescription(status: KeyStatus): string {
  switch (status.source) {
    case "database":
      return `Saved in Settings (…${status.last4})${status.updated_at ? `, updated ${formatDateTime(status.updated_at)}` : ""}.`
    case "environment":
      return `Using RAG_OPENAI_API_KEY from deploy/.env (…${status.last4}).`
    case "unreadable":
      return "The saved key can't be decrypted with the current RAG_SECRETS_KEY; RAG_OPENAI_API_KEY is used if set. Save the key again."
    default:
      return "No key is configured: chat, ingestion and evaluation won't work until you add one."
  }
}

function OpenAIKeyCard() {
  const queryClient = useQueryClient()
  const { data: status } = useQuery({ queryKey: ["admin", "openai-key"], queryFn: adminApi.openaiKey })
  const [key, setKey] = useState("")
  const [confirming, setConfirming] = useState<"save" | "clear" | null>(null)
  const apply = (next: KeyStatus) => queryClient.setQueryData(["admin", "openai-key"], next)
  if (!status) return null
  const disabled = !status.secrets_key_configured
  return (
    <Card>
      <CardHeader>
        <CardTitle>OpenAI API key</CardTitle>
        <CardDescription>
          Encrypted at rest; only the last 4 characters are ever shown. Every service picks up a new
          key within 30 seconds.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-sm">{keyDescription(status)}</p>
        {disabled && (
          <Alert>
            <AlertDescription>
              Set RAG_SECRETS_KEY in deploy/.env (a Fernet key) and restart to save keys here.
            </AlertDescription>
          </Alert>
        )}
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (key.trim().length >= 20) setConfirming("save")
          }}
        >
          <Field className="min-w-72 flex-1">
            <FieldLabel htmlFor="openai-key">New OpenAI API key</FieldLabel>
            <Input
              id="openai-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              disabled={disabled}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={disabled || key.trim().length < 20}>
            Save key
          </Button>
          {(status.source === "database" || status.source === "unreadable") && (
            <Button type="button" variant="ghost" onClick={() => setConfirming("clear")}>
              Remove saved key
            </Button>
          )}
        </form>
      </CardContent>
      <PasswordDialog
        open={confirming === "save"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Save the OpenAI API key?"
        description="It replaces the key every answer, upload and evaluation uses."
        confirmLabel="Save key securely"
        onConfirm={async (password) => {
          apply(await adminApi.setOpenaiKey(key.trim(), password))
          setKey("")
          toast.success("API key saved")
        }}
      />
      <PasswordDialog
        open={confirming === "clear"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Remove the saved key?"
        description="The installation falls back to RAG_OPENAI_API_KEY from deploy/.env, if set."
        confirmLabel="Remove key"
        destructive
        onConfirm={async (password) => {
          apply(await adminApi.clearOpenaiKey(password))
          toast.success("Saved key removed")
        }}
      />
    </Card>
  )
}

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Installation-wide settings. Cost caps and the fallback model are versioned with the RAG config."
      />
      <SuperAdminOnly>
        <div className="grid gap-6">
          <BrandingCard />
          <OpenAIKeyCard />
        </div>
      </SuperAdminOnly>
    </>
  )
}
```

The key isn't put into react-hook-form, so it never enters form state snapshots or devtools. It lives in one `useState` and is cleared after saving. Spec §6.5 lists cost caps and the fallback model under Settings. They stay on the Guardrails and Models pages because they are versioned with the RAG config (Plan 4 ruling), and the header says so.

- [ ] **Step 3: Run the tests and checks**

Run: `npm test && npm run lint && npm run typecheck && npm run build`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/admin/settings
git commit -m "feat(admin): settings page for branding, logo and encrypted OpenAI key"
```

---

### Task 12: Real-stack end-to-end check and follow-ups

**Files:**
- Create: `frontend/e2e/admin.spec.ts`, `frontend/e2e/fixtures/e2e-handbook.md`
- Modify: `deploy/.env.example` (add `RAG_SECRETS_KEY`), and the frontend env docs if any exist (`NEXT_PUBLIC_PHOENIX_URL`)
- Create: `docs/superpowers/plans/2026-10-08-plan-7-followups.md`

**Interfaces:**
- Consumes: the running stack (`deploy/docker-compose.yml`: api, worker, worker-eval, postgres, qdrant, redis, clamav, phoenix), the frontend (`npm run build && npm start`), and the super admin from `make create-superadmin`, or the existing `E2E_USERNAME`/`E2E_PASSWORD`.
- Produces: `npm run e2e` covering the spec §9 "admin upload → status reaches `ready`" flow, and the follow-ups doc.

- [ ] **Step 1: Document the new settings**

In `deploy/.env.example`, under the OpenAI key, add:

```
# Encrypts API keys saved in admin Settings (Fernet). Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Changing it makes saved keys unreadable (Settings shows this; save them again).
RAG_SECRETS_KEY=
```

Check that `deploy/docker-compose.yml` passes the `RAG_*` env to `api`, `worker` and `worker-eval` (via `env_file`). If any service lists variables explicitly, add `RAG_SECRETS_KEY` there.

- [ ] **Step 2: Write the end-to-end test**

`frontend/e2e/fixtures/e2e-handbook.md`:

```markdown
# Travel handbook

Employees booking flights longer than six hours may travel in premium economy.
Hotel stays are reimbursed up to 180 euros per night in capital cities.
```

`frontend/e2e/admin.spec.ts`:

```ts
import path from "node:path"

import { expect, test } from "@playwright/test"

const username = process.env.E2E_USERNAME ?? "root"
const password = process.env.E2E_PASSWORD ?? "root-password-123"

test("admin creates a collection, uploads a document and sees it become ready", async ({ page }) => {
  await page.goto("/admin")
  await expect(page).toHaveURL(/\/login/)
  await page.getByLabel("Username").fill(username)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible()

  const name = `E2E ${Date.now()}`
  await page.getByRole("link", { name: "Collections & access" }).click()
  await page.getByRole("button", { name: "New collection" }).click()
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText(name)).toBeVisible()

  await page.getByRole("link", { name: "Documents" }).click()
  await page.getByLabel("Collection").selectOption({ label: name })
  await page
    .getByLabel("Upload files")
    .setInputFiles(path.join(__dirname, "fixtures", "e2e-handbook.md"))
  await expect(page.getByText("1 of 1 files queued for processing")).toBeVisible()
  const row = page.getByRole("row", { name: /e2e-handbook\.md/ })
  await expect(row.getByText("Ready")).toBeVisible({ timeout: 180_000 })

  await row.getByRole("button", { name: "e2e-handbook.md" }).click()
  await expect(page.getByText(/premium economy/)).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("link", { name: "Audit log" }).click()
  await page.getByLabel("Action starts with").fill("document.")
  await page.getByRole("button", { name: "Apply" }).click()
  await expect(page.getByRole("cell", { name: "document.uploaded" }).first()).toBeVisible()
})
```

If `__dirname` isn't defined (ESM, because `package.json` has `"type": "module"`), use `path.join(import.meta.dirname, "fixtures", "e2e-handbook.md")`.

- [ ] **Step 3: Run it on the real stack**

1. Start the backend stack with the existing compose setup, which already has the OpenAI key. Set `RAG_SECRETS_KEY` in `deploy/.env` with a newly generated key, and **never print the file**. Then `docker compose -f deploy/docker-compose.yml up -d --build`.
2. Run the frontend: `cd frontend && npm run build && npm start`.
3. Run `E2E_USERNAME=… E2E_PASSWORD=… npm run e2e`. Expected: 2 passed (the Plan 6 smoke test and this one).
4. Check by hand in the browser, and record the results in the follow-ups doc:
   - Settings → upload a PNG logo and set the color `#0f766e`. The sidebar and the sign-in page show them.
   - Save the OpenAI key from `deploy/.env` through the form, re-entering the password. Settings shows "Saved in Settings (…xxxx)", and asking a question in `/app` still works. Remove the saved key, and Settings shows "Using RAG_OPENAI_API_KEY".
   - Models → save a version with a changed `rerank_top_n`. The activation dialog shows the eval scores, then roll back to the previous version.
   - Dashboard → the figures are non-zero after the questions above, and health shows all `ok`.

- [ ] **Step 4: Write the follow-ups doc**

`docs/superpowers/plans/2026-10-08-plan-7-followups.md`, in the same shape as `2026-10-08-plan-6-followups.md`. Its sections:

- **Carry into Plan 8 (production packaging):**
  - `RAG_SECRETS_KEY` is required to save keys. Back it up with the database: without it, saved keys are unreadable.
  - The logo lives in the files volume at `branding/logo`, so backups must include it.
  - `NEXT_PUBLIC_PHOENIX_URL` is a frontend build-time variable.
  - CSP: `img-src 'self'` covers the logo, and the audit CSV export is a same-origin download.
  - The admin pages poll every 5 s while documents or eval runs are in progress.
  - The extra e2e test needs the worker and an OpenAI key in CI, or is skipped there.
- **Rulings made during execution:** copy them from the SDD ledger.
- **End-to-end result:** the Playwright output and the manual checks from Step 3.
- **Deferred minor findings:** copy them from the ledger.

- [ ] **Step 5: Final verification and commit**

Run:
- `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`

Expected: all green.

```bash
git add frontend/e2e/admin.spec.ts frontend/e2e/fixtures/e2e-handbook.md deploy/.env.example docs/superpowers/plans/2026-10-08-plan-7-followups.md
git commit -m "test(e2e): admin upload reaches ready; docs: plan 7 follow-ups"
```
