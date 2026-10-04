import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth import service as auth
from app.auth.tokens import TokenError, create_access_token, decode_access_token
from app.core.config import Settings
from app.users.models import User
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

# Routes reachable without a token. Adding one must be a deliberate, reviewed decision.
PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}


# ---------- tokens ----------


def test_token_roundtrip_and_rejections(settings: Settings) -> None:
    user = User(id=uuid.uuid4(), username="u", role="user", token_version=3)
    assert decode_access_token(create_access_token(user, settings), settings) == (user.id, 3)

    expired = create_access_token(user, settings, now=datetime.now(UTC) - timedelta(hours=9))
    with pytest.raises(TokenError):
        decode_access_token(expired, settings)
    other = Settings(_env_file=None, jwt_secret="z" * 40)
    with pytest.raises(TokenError):
        decode_access_token(create_access_token(user, other), settings)
    with pytest.raises(TokenError):
        decode_access_token("not.a.jwt", settings)


# ---------- authenticate() ----------


async def test_login_is_case_and_space_insensitive(
    session: AsyncSession, settings: Settings
) -> None:
    await make_user(session, username="alice")
    user = await auth.authenticate(
        session, username="  Alice ", password=DEFAULT_PASSWORD, settings=settings
    )
    assert user.username == "alice"
    assert (await audit.list_recent(session))[0].action == "auth.login_succeeded"


async def test_wrong_password_locks_after_max_attempts(
    session: AsyncSession, settings: Settings
) -> None:
    # settings fixture: login_max_failed_attempts=3, lockout 900 s
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for _ in range(2):
        with pytest.raises(auth.InvalidCredentials):
            await auth.authenticate(
                session, username="alice", password="wrong", settings=settings, now=now
            )
    with pytest.raises(auth.AccountLocked) as locked:
        await auth.authenticate(
            session, username="alice", password="wrong", settings=settings, now=now
        )
    assert locked.value.until == now + timedelta(seconds=900)
    assert user.failed_login_count == 0


async def test_lock_blocks_correct_password_until_expiry(
    session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(session, username="alice")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    user.locked_until = now + timedelta(minutes=15)
    await session.commit()
    with pytest.raises(auth.AccountLocked):
        await auth.authenticate(
            session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=now
        )
    later = now + timedelta(minutes=15, seconds=1)
    result = await auth.authenticate(
        session, username="alice", password=DEFAULT_PASSWORD, settings=settings, now=later
    )
    assert result.locked_until is None


async def test_unknown_and_disabled_users(session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(auth.InvalidCredentials):
        await auth.authenticate(session, username="ghost", password="x", settings=settings)
    await make_user(session, username="off", is_active=False)
    with pytest.raises(auth.InvalidCredentials):  # wrong password doesn't reveal "disabled"
        await auth.authenticate(session, username="off", password="wrong", settings=settings)
    with pytest.raises(auth.AccountDisabled):
        await auth.authenticate(
            session, username="off", password=DEFAULT_PASSWORD, settings=settings
        )


# ---------- HTTP API ----------


async def test_login_api(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    ok = await client.post(
        "/api/auth/login", json={"username": "alice", "password": DEFAULT_PASSWORD}
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 60 * 60
    assert body["user"]["username"] == "alice"
    assert "password_hash" not in body["user"]

    bad = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "invalid_credentials"


async def test_failed_logins_are_persisted_and_lock(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await make_user(session, username="alice")
    for _ in range(2):
        await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    locked = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "account_locked"
    await session.refresh(user)
    assert user.locked_until is not None


async def test_me_requires_valid_token(client: AsyncClient, session: AsyncSession) -> None:
    assert (await client.get("/api/auth/me")).json()["detail"]["code"] == "not_authenticated"
    assert (await client.get("/api/auth/me", headers=bearer("garbage"))).status_code == 401
    await make_user(session, username="alice")
    me = await client.get("/api/auth/me", headers=bearer(await login(client, "alice")))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_forced_password_change_flow(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="newbie", must_change_password=True)
    first = await client.post(
        "/api/auth/login", json={"username": "newbie", "password": DEFAULT_PASSWORD}
    )
    assert first.json()["must_change_password"] is True
    token = first.json()["access_token"]

    # /me works so the frontend can show the change-password screen
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 200

    wrong = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": "wrong", "new_password": "fresh-secret-99"},
    )
    assert wrong.status_code == 400
    weak = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert weak.json()["detail"]["code"] == "weak_password"

    changed = await client.post(
        "/api/auth/change-password",
        headers=bearer(token),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "fresh-secret-99"},
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False
    # the old token is revoked; the new one works
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    new_token = changed.json()["access_token"]
    assert (await client.get("/api/auth/me", headers=bearer(new_token))).status_code == 200


# ---------- route guard ----------
# Behavioral: every operation in the OpenAPI schema is actually called, so a new route
# cannot slip through regardless of how FastAPI organizes routers internally.


def _operations(app: FastAPI) -> list[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return [(method.upper(), path) for path, ops in paths.items() for method in ops]


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


async def test_every_non_public_route_requires_authentication(
    app: FastAPI, client: AsyncClient
) -> None:
    operations = _operations(app)
    assert PUBLIC_ROUTES <= set(operations)
    unprotected = []
    for method, path in operations:
        if (method, path) in PUBLIC_ROUTES:
            continue
        response = await client.request(method, _concrete(path), json={})
        if response.status_code != 401:
            unprotected.append(f"{method} {path} -> {response.status_code}")
    assert unprotected == []


async def test_every_admin_route_requires_admin_role(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="plain")
    token = await login(client, "plain")
    admin_ops = [(m, p) for m, p in _operations(app) if p.startswith("/api/admin")]
    allowed = []
    for method, path in admin_ops:
        response = await client.request(method, _concrete(path), headers=bearer(token), json={})
        if response.status_code != 403:
            allowed.append(f"{method} {path} -> {response.status_code}")
    assert allowed == []
