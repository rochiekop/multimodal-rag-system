import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

CSRF = {"X-CSRF-Protection": "1"}


async def _sign_in(client: AsyncClient, username: str = "alice"):
    return await client.post(
        "/api/auth/session", json={"username": username, "password": DEFAULT_PASSWORD}
    )


async def test_sign_in_sets_an_httponly_strict_cookie_and_hides_the_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    response = await _sign_in(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" not in body
    assert body["user"]["username"] == "alice" and body["must_change_password"] is False
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("rag_session=")
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "max-age=28800" in cookie
    assert "secure" not in cookie  # settings fixture runs with env=test


async def test_cookie_authenticates_reads_and_csrf_guards_writes(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    await _sign_in(client)  # the client keeps the cookie
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "alice"

    url = f"/api/messages/{uuid.uuid4()}/feedback"
    blocked = await client.post(url, json={"rating": 1})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "csrf_required"
    allowed = await client.post(url, json={"rating": 1}, headers=CSRF)
    assert allowed.status_code == 404  # passed auth + CSRF; the message just doesn't exist


async def test_bearer_requests_need_no_csrf_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="alice")
    token = await login(client, "alice")
    client.cookies.clear()
    response = await client.post(
        f"/api/messages/{uuid.uuid4()}/feedback", json={"rating": 1}, headers=bearer(token)
    )
    assert response.status_code == 404


async def test_sign_out_clears_the_cookie(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    await _sign_in(client)
    out = await client.delete("/api/auth/session")
    assert out.status_code == 204
    assert "rag_session=" in out.headers["set-cookie"].lower()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_works_without_a_valid_session(client: AsyncClient) -> None:
    client.cookies.set("rag_session", "garbage")
    out = await client.delete("/api/auth/session")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_bad_credentials_set_no_cookie(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="alice")
    response = await client.post(
        "/api/auth/session", json={"username": "alice", "password": "wrong"}
    )
    assert response.status_code == 401 and "set-cookie" not in response.headers


async def test_forced_password_change_refreshes_the_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, username="newbie", must_change_password=True)
    first = await _sign_in(client, "newbie")
    assert first.json()["must_change_password"] is True
    old_token = client.cookies.get("rag_session")
    assert (await client.get("/api/collections")).status_code == 403  # change required first

    changed = await client.post(
        "/api/auth/session/password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "a-much-better-pass-99"},
        headers=CSRF,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False
    assert client.cookies.get("rag_session") != old_token
    assert (await client.get("/api/collections")).status_code == 200
    stale = await client.get("/api/auth/me", headers=bearer(str(old_token)))
    assert stale.status_code == 401  # the old token was revoked by the change
