import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.security import WeakPasswordError, verify_password
from app.users import service as users
from app.users.models import Role
from tests.factories import make_group, make_user

STRONG = "brand-new-pass-77"


async def test_create_user(session: AsyncSession) -> None:
    group = await make_group(session, "hr")
    user = await users.create_user(
        session,
        actor=None,
        username="new.person",
        full_name=" New Person ",
        password=STRONG,
        group_ids=[group.id],
    )
    await session.commit()
    assert user.full_name == "New Person"
    assert user.role == "user"
    assert user.must_change_password is True
    assert verify_password(user.password_hash, STRONG)
    assert [g.name for g in user.groups] == ["hr"]
    entry = (await audit.list_recent(session))[0]
    assert entry.action == "user.created"
    assert "password" not in str(entry.detail)


async def test_username_is_normalized_and_unique(session: AsyncSession) -> None:
    user = await users.create_user(
        session, actor=None, username="  Alice ", full_name="A", password=STRONG
    )
    assert user.username == "alice"
    with pytest.raises(users.UsernameTaken):
        await users.create_user(
            session, actor=None, username="ALICE", full_name="B", password=STRONG
        )


@pytest.mark.parametrize("bad", ["ab", "has space", "x" * 65, "semi;colon"])
async def test_invalid_usernames_rejected(session: AsyncSession, bad: str) -> None:
    with pytest.raises(users.InvalidUsername):
        await users.create_user(session, actor=None, username=bad, full_name="X", password=STRONG)


async def test_weak_password_and_unknown_group_rejected(session: AsyncSession) -> None:
    with pytest.raises(WeakPasswordError):
        await users.create_user(
            session, actor=None, username="weak", full_name="W", password="short"
        )
    with pytest.raises(users.GroupNotFound):
        await users.create_user(
            session,
            actor=None,
            username="nogroup",
            full_name="N",
            password=STRONG,
            group_ids=[uuid.uuid4()],
        )


async def test_role_rules_for_creating_users(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    plain = await make_user(session, username="plain")

    worker = await users.create_user(
        session, actor=admin, username="worker", full_name="W", password=STRONG
    )
    assert worker.role == "user"
    with pytest.raises(users.PermissionDenied):
        await users.create_user(
            session, actor=admin, username="admin2", full_name="A", password=STRONG, role=Role.ADMIN
        )
    with pytest.raises(users.PermissionDenied):
        await users.create_user(
            session, actor=plain, username="other", full_name="O", password=STRONG
        )
    promoted = await users.create_user(
        session, actor=root, username="admin3", full_name="A", password=STRONG, role=Role.ADMIN
    )
    assert promoted.role == "admin"


async def test_update_role_and_groups(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    eng = await make_group(session, "eng")
    target = await make_user(session, username="target")
    updated = await users.update_user(
        session, actor=root, user_id=target.id, role=Role.ADMIN, group_ids=[eng.id]
    )
    assert updated.role == "admin"
    assert updated.token_version == 1
    assert [g.name for g in updated.groups] == ["eng"]


async def test_admin_cannot_edit_admins_or_promote(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    other_admin = await make_user(session, username="admin2", role=Role.ADMIN)
    plain = await make_user(session, username="plain")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=other_admin.id, full_name="X")
    with pytest.raises(users.PermissionDenied):
        await users.update_user(session, actor=admin, user_id=plain.id, role=Role.ADMIN)


async def test_cannot_change_own_role_or_deactivate_self(session: AsyncSession) -> None:
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    with pytest.raises(users.PermissionDenied, match="own role"):
        await users.update_user(session, actor=root, user_id=root.id, role=Role.USER)
    with pytest.raises(users.PermissionDenied, match="yourself"):
        await users.update_user(session, actor=root, user_id=root.id, is_active=False)


async def test_deactivate_revokes_tokens_and_unlock_clears_lock(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    target.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    target.failed_login_count = 2
    await session.commit()

    updated = await users.update_user(
        session, actor=admin, user_id=target.id, is_active=False, unlock=True
    )
    assert updated.is_active is False
    assert updated.token_version == 1
    assert updated.locked_until is None
    assert updated.failed_login_count == 0


async def test_update_unknown_user(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    with pytest.raises(users.NotFound):
        await users.update_user(session, actor=admin, user_id=uuid.uuid4(), full_name="X")


async def test_reset_password_forces_change_and_revokes(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    target = await make_user(session, username="target")
    reset = await users.reset_password(
        session, actor=admin, user_id=target.id, new_password="temporary-pass-11"
    )
    assert verify_password(reset.password_hash, "temporary-pass-11")
    assert reset.must_change_password is True
    assert reset.token_version == 1


async def test_groups(session: AsyncSession) -> None:
    admin = await make_user(session, username="admin1", role=Role.ADMIN)
    group = await users.create_group(session, actor=admin, name=" Finance ", description="money")
    assert group.name == "Finance"
    with pytest.raises(users.GroupNameTaken):
        await users.create_group(session, actor=admin, name="Finance")
    assert [g.name for g in await users.list_groups(session)] == ["Finance"]
