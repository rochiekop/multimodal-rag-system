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
        User(
            username="bob",
            full_name="Bob",
            password_hash="x",
            role="user",
            groups=[Group(name="hr")],
        )
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
        session,
        action="second",
        actor=actor,
        target_type="user",
        target_id=actor.id,
        detail={"k": 1},
    )
    await session.commit()

    assert entry.actor_username == "carol"
    assert entry.target_id == str(actor.id)
    assert [e.action for e in await audit.list_recent(session)] == ["second", "first"]


async def test_audit_log_is_append_only(session: AsyncSession) -> None:
    entry_id = (await audit.record(session, action="event")).id
    await session.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(update(AuditLog).where(AuditLog.id == entry_id).values(action="x"))
    await session.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(delete(AuditLog).where(AuditLog.id == entry_id))
    await session.rollback()
