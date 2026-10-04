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
