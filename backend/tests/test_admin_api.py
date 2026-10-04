import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import Role
from tests.factories import bearer, login, make_group, make_user

NEW_PASSWORD = "initial-pass-123"


async def _admin_token(client: AsyncClient, session: AsyncSession) -> str:
    await make_user(session, username="admin1", role=Role.ADMIN)
    return await login(client, "admin1")


async def test_non_admins_are_blocked(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="plain")
    response = await client.get("/api/admin/users", headers=bearer(await login(client, "plain")))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"

    await make_user(session, username="admin9", role=Role.ADMIN, must_change_password=True)
    pending = await client.get("/api/admin/users", headers=bearer(await login(client, "admin9")))
    assert pending.json()["detail"]["code"] == "password_change_required"


async def test_admin_creates_user_who_must_change_password(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _admin_token(client, session)
    group = await make_group(session, "hr")
    created = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={
            "username": "Worker",
            "full_name": "Worker One",
            "password": NEW_PASSWORD,
            "group_ids": [str(group.id)],
        },
    )
    assert created.status_code == 201
    assert created.json()["username"] == "worker"
    assert created.json()["must_change_password"] is True
    assert [g["name"] for g in created.json()["groups"]] == ["hr"]

    first_login = await client.post(
        "/api/auth/login", json={"username": "worker", "password": NEW_PASSWORD}
    )
    assert first_login.json()["must_change_password"] is True

    listed = await client.get("/api/admin/users", headers=bearer(token))
    assert [u["username"] for u in listed.json()] == ["admin1", "worker"]


async def test_create_user_errors(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    base = {"username": "worker", "full_name": "W", "password": NEW_PASSWORD}
    weak = await client.post(
        "/api/admin/users", headers=bearer(token), json={**base, "password": "short"}
    )
    assert weak.json()["detail"]["code"] == "weak_password"
    first = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert first.status_code == 201
    duplicate = await client.post("/api/admin/users", headers=bearer(token), json=base)
    assert duplicate.status_code == 409
    bad_group = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={**base, "username": "other", "group_ids": [str(uuid.uuid4())]},
    )
    assert bad_group.json()["detail"]["code"] == "group_not_found"


async def test_admin_cannot_promote_to_admin(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    plain = await make_user(session, username="plain")
    promote = await client.patch(
        f"/api/admin/users/{plain.id}", headers=bearer(token), json={"role": "admin"}
    )
    assert promote.status_code == 403
    create_admin = await client.post(
        "/api/admin/users",
        headers=bearer(token),
        json={"username": "sneaky", "full_name": "S", "password": NEW_PASSWORD, "role": "admin"},
    )
    assert create_admin.status_code == 403


async def test_super_admin_promotes_user(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    plain = await make_user(session, username="plain")
    response = await client.patch(
        f"/api/admin/users/{plain.id}",
        headers=bearer(await login(client, "root")),
        json={"role": "admin"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_deactivated_user_token_is_rejected_immediately(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin_token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    target_token = await login(client, "target")
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 200

    off = await client.patch(
        f"/api/admin/users/{target.id}", headers=bearer(admin_token), json={"is_active": False}
    )
    assert off.json()["is_active"] is False
    assert (await client.get("/api/auth/me", headers=bearer(target_token))).status_code == 401


async def test_unlock_and_reset_password(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    target = await make_user(session, username="target")
    for _ in range(3):
        await client.post("/api/auth/login", json={"username": "target", "password": "nope"})

    unlocked = await client.patch(
        f"/api/admin/users/{target.id}", headers=bearer(token), json={"unlock": True}
    )
    assert unlocked.json()["locked_until"] is None

    reset = await client.post(
        f"/api/admin/users/{target.id}/reset-password",
        headers=bearer(token),
        json={"new_password": "temporary-pass-11"},
    )
    assert reset.json()["must_change_password"] is True
    relogin = await client.post(
        "/api/auth/login", json={"username": "target", "password": "temporary-pass-11"}
    )
    assert relogin.status_code == 200

    missing = await client.patch(
        f"/api/admin/users/{uuid.uuid4()}", headers=bearer(token), json={"unlock": True}
    )
    assert missing.status_code == 404


async def test_groups_and_audit(client: AsyncClient, session: AsyncSession) -> None:
    token = await _admin_token(client, session)
    created = await client.post("/api/admin/groups", headers=bearer(token), json={"name": "Legal"})
    assert created.status_code == 201
    duplicate = await client.post(
        "/api/admin/groups", headers=bearer(token), json={"name": "Legal"}
    )
    assert duplicate.status_code == 409
    groups = await client.get("/api/admin/groups", headers=bearer(token))
    assert [g["name"] for g in groups.json()] == ["Legal"]

    entries = (await client.get("/api/admin/audit", headers=bearer(token))).json()
    assert entries[0]["action"] == "group.created"
    assert entries[0]["actor_username"] == "admin1"
    assert entries[0]["detail"] == {"name": "Legal"}
