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
