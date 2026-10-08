import io
import json
import logging
import re

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.logging import json_handler, request_id_var
from tests.factories import DEFAULT_PASSWORD, make_user


async def test_request_id_is_generated_echoed_or_replaced(client: AsyncClient) -> None:
    generated = await client.get("/api/health")
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["x-request-id"])

    echoed = await client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["x-request-id"] == "abc-123"

    replaced = await client.get("/api/health", headers={"X-Request-ID": "bad id!"})
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["x-request-id"])


def test_json_logs_include_the_request_id() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("test.jsonlog")
    logger.handlers[:] = [json_handler(stream)]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    token = request_id_var.set("req-42")
    try:
        logger.info("hello", extra={"doc": "x"})
    finally:
        request_id_var.reset(token)
    line = json.loads(stream.getvalue())
    assert line["message"] == "hello"
    assert line["request_id"] == "req-42"
    assert line["levelname"] == "INFO"
    assert line["doc"] == "x"


async def test_audit_entries_carry_the_request_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    response = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": DEFAULT_PASSWORD},
        headers={"X-Request-ID": "req-audit-1"},
    )
    assert response.status_code == 200
    entry = await session.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    assert entry is not None and entry.request_id == "req-audit-1"


async def test_unhandled_error_returns_json_500_with_request_id(app, caplog) -> None:
    from httpx import ASGITransport

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
        await client.get("/api/no-such-route", headers={"X-Request-ID": "req-log"})
    records = [r for r in caplog.records if r.name == "app.access"]
    assert len(records) == 1
    record = records[0]
    assert (record.method, record.path, record.status) == ("GET", "/api/no-such-route", 404)
    assert record.duration_ms >= 0

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="app.access"):
        await client.get("/api/health")
    assert [r.path for r in caplog.records if r.name == "app.access"] == ["/api/health"]


def test_bm25_path_resolution(tmp_path, monkeypatch) -> None:
    from app.llm import sparse

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    assert sparse.cached_bm25_path() is None
    repo = tmp_path / "models--Qdrant--bm25"
    (repo / "snapshots" / "abc").mkdir(parents=True)
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("abc")
    assert sparse.cached_bm25_path() == str(repo / "snapshots" / "abc")
