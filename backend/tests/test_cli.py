import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.core.config import get_settings
from app.core.db import create_sessionmaker
from app.core.security import verify_password


async def test_create_superadmin(engine: AsyncEngine) -> None:
    user = await cli.create_superadmin(
        create_sessionmaker(engine),
        username="Root",
        full_name="Root Admin",
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
