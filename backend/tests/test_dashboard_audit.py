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
            UsageRecord(
                user_id=alice.id,
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.5,
                created_at=today,
            ),
            UsageRecord(
                user_id=bob.id,
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.25,
                created_at=yesterday,
            ),
            GuardrailEvent(
                user_id=bob.id, check="moderation", action="blocked", created_at=yesterday
            ),
            GuardrailEvent(
                user_id=bob.id, check="moderation", action="flagged", created_at=yesterday
            ),
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
        await audit.record(
            session, action="user.created", actor=admin, target_type="user", target_id=f"u{i}"
        )
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
    await audit.record(
        session,
        action="user.created",
        target_id='=HYPERLINK("http://x")',
        detail={"note": "+1"},
    )
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
