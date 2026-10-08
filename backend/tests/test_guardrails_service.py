from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.guardrails import service as guardrails
from app.guardrails.models import GuardrailEvent, Notification
from app.guardrails.settings import GuardrailSettings
from app.llm.rag_config import RagConfig
from app.users.models import Role, User
from tests.factories import bearer, login, make_user

SETTINGS = GuardrailSettings()


async def _block(session: AsyncSession, user: User) -> guardrails.StrikeResult:
    result = await guardrails.record_event(
        session,
        user=user,
        check="prompt_injection",
        action="blocked",
        strike=True,
        settings=SETTINGS,
    )
    await session.commit()
    return result


async def test_third_strike_locks_chat_and_notifies_admins(session: AsyncSession) -> None:
    alice = await make_user(session, username="alice")
    first = await _block(session, alice)
    second = await _block(session, alice)
    assert (first.strikes, first.locked_until) == (1, None)
    assert (second.strikes, second.locked_until) == (2, None)

    third = await _block(session, alice)
    assert third.strikes == 3 and third.locked_until is not None
    lock_hours = (third.locked_until - datetime.now(UTC)).total_seconds() / 3600
    assert 23.9 < lock_hours <= 24

    await session.refresh(alice)
    assert alice.chat_locked_until == third.locked_until
    notes = (await session.scalars(select(Notification))).all()
    assert [n.kind for n in notes] == ["strike_lock"]
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert actions.count("guardrail.blocked") == 3
    assert "guardrail.strike_lock" in actions


async def test_flags_and_old_strikes_do_not_count(session: AsyncSession) -> None:
    alice = await make_user(session, username="alice")
    session.add(
        GuardrailEvent(
            user_id=alice.id,
            check="moderation",
            action="blocked",
            strike=True,
            created_at=datetime.now(UTC) - timedelta(hours=25),
        )
    )
    await session.commit()
    flagged = await guardrails.record_event(
        session, user=alice, check="pii", action="flagged", settings=SETTINGS
    )
    await session.commit()
    assert flagged.strikes == 0
    assert (await _block(session, alice)).strikes == 1


async def test_admin_unlock_clears_chat_lock_and_strikes(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice = await make_user(session, username="alice")
    await make_user(session, username="boss", role=Role.ADMIN)
    for _ in range(3):
        await _block(session, alice)
    token = await login(client, "boss")

    response = await client.patch(
        f"/api/admin/users/{alice.id}", headers=bearer(token), json={"unlock": True}
    )
    assert response.status_code == 200, response.text
    assert response.json()["chat_locked_until"] is None
    assert (await _block(session, alice)).strikes == 1  # slate wiped by the unlock

    # Below the limit nothing is locked, so only the unlock itself can wipe the slate.
    bob = await make_user(session, username="bob")
    for _ in range(2):
        await _block(session, bob)
    response = await client.patch(
        f"/api/admin/users/{bob.id}", headers=bearer(token), json={"unlock": True}
    )
    assert response.status_code == 200, response.text
    assert (await _block(session, bob)).strikes == 1


async def test_notifications_api_lists_and_marks_read(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="boss", role=Role.ADMIN)
    await guardrails.notify(session, kind="cost_alert", title="A", dedupe_key="k1")
    await guardrails.notify(session, kind="cost_alert", title="A again", dedupe_key="k1")
    await guardrails.notify(session, kind="strike_lock", title="B")
    await session.commit()
    token = await login(client, "boss")

    listed = (await client.get("/api/admin/notifications", headers=bearer(token))).json()
    assert [n["title"] for n in listed] == ["B", "A"]  # newest first, duplicate dropped
    read = await client.post(
        f"/api/admin/notifications/{listed[0]['id']}/read", headers=bearer(token)
    )
    assert read.status_code == 200 and read.json()["read_at"] is not None
    unread = await client.get(
        "/api/admin/notifications", headers=bearer(token), params={"unread": "true"}
    )
    assert [n["title"] for n in unread.json()] == ["A"]


def test_settings_validate_patterns_and_old_configs_get_defaults() -> None:
    with pytest.raises(ValidationError):
        GuardrailSettings(pii_patterns=[{"name": "bad", "regex": "(unclosed"}])
    with pytest.raises(ValidationError):
        GuardrailSettings(moderation={"violence": "maybe"})
    old = RagConfig.model_validate({"chat_model": "gpt-5-mini"})  # stored before Plan 4
    assert old.guardrails == GuardrailSettings() and old.fallback_model is None
    assert GuardrailSettings().moderation["self_harm"] == "flag"


async def test_concurrent_final_strikes_notify_once(session: AsyncSession) -> None:
    alice = await make_user(session, username="alice")
    for _ in range(2):
        await _block(session, alice)
    first = await _block(session, alice)
    # A racing request counted its final strike before the first lock wiped the slate.
    await session.execute(update(User).where(User.id == alice.id).values(strike_reset_at=None))
    await session.commit()
    second = await _block(session, alice)
    assert first.locked_until is not None and second.locked_until is not None

    notes = (await session.scalars(select(Notification))).all()
    same_hour = f"{first.locked_until:%Y%m%d%H}" == f"{second.locked_until:%Y%m%d%H}"
    assert len(notes) == (1 if same_hour else 2)
    assert notes[0].dedupe_key == f"strike_lock:{alice.id}:{first.locked_until:%Y%m%d%H}"
