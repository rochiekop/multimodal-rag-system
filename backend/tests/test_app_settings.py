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


async def test_branding_defaults_update_and_logo(session: AsyncSession, settings: Settings) -> None:
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
