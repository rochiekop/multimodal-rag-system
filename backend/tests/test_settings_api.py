import io

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import Role
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

SECRET = "sk-live-abcdefghijklmnop9876"


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


async def _root(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    return bearer(await login(client, "root"))


@pytest.fixture
def with_secrets_key(app: FastAPI) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"secrets_key": SecretStr(Fernet.generate_key().decode())}
    )


async def test_settings_are_super_admin_only(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="admin1", role=Role.ADMIN)
    headers = bearer(await login(client, "admin1"))
    for method, path in [
        ("GET", "/api/admin/settings/openai-key"),
        ("PUT", "/api/admin/settings/branding"),
    ]:
        response = await client.request(method, path, headers=headers, json={})
        assert response.status_code == 403, path


async def test_branding_roundtrip_is_public(client: AsyncClient, session: AsyncSession) -> None:
    headers = await _root(client, session)
    assert (await client.get("/api/branding")).json() == {
        "app_name": "Knowledge Assistant",
        "primary_color": None,
        "logo_url": None,
    }
    bad = await client.put(
        "/api/admin/settings/branding",
        headers=headers,
        json={"app_name": "Acme", "primary_color": "red; background:url(x)"},
    )
    assert bad.status_code == 422
    saved = await client.put(
        "/api/admin/settings/branding",
        headers=headers,
        json={"app_name": "Acme", "primary_color": "#0F766E"},
    )
    assert saved.status_code == 200
    assert (await client.get("/api/branding")).json()["primary_color"] == "#0F766E"


async def test_logo_rejects_non_images_and_svg(client: AsyncClient, session: AsyncSession) -> None:
    headers = await _root(client, session)
    for name, data in [("x.svg", b"<svg onload=alert(1)/>"), ("x.png", b"<html></html>")]:
        response = await client.post(
            "/api/admin/settings/branding/logo",
            headers=headers,
            files={"file": (name, data, "image/png")},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_logo"
    assert (await client.get("/api/branding/logo")).status_code == 404

    uploaded = await client.post(
        "/api/admin/settings/branding/logo",
        headers=headers,
        files={"file": ("logo.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200
    logo = await client.get(uploaded.json()["logo_url"])
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.headers["x-content-type-options"] == "nosniff"
    assert logo.content == _png()

    removed = await client.delete("/api/admin/settings/branding/logo", headers=headers)
    assert removed.json()["logo_url"] is None


async def test_openai_key_endpoints_never_echo_the_key(
    app: FastAPI, client: AsyncClient, session: AsyncSession, with_secrets_key: None
) -> None:
    headers = await _root(client, session)
    wrong = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": "wrong-password-1"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["code"] == "password_confirmation_failed"

    saved = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": DEFAULT_PASSWORD},
    )
    assert saved.status_code == 200
    assert saved.json()["source"] == "database"
    assert saved.json()["last4"] == "9876"
    assert SECRET not in saved.text
    assert app.state.keys.openai().get_secret_value() == SECRET  # refreshed at once

    status = await client.get("/api/admin/settings/openai-key", headers=headers)
    assert SECRET not in status.text
    audit = await client.get("/api/admin/audit", headers=headers)
    assert SECRET not in audit.text

    cleared = await client.post(
        "/api/admin/settings/openai-key/clear",
        headers=headers,
        json={"password": DEFAULT_PASSWORD},
    )
    assert cleared.json()["source"] == "none"


async def test_saving_a_key_without_secrets_key_is_409(
    client: AsyncClient, session: AsyncSession
) -> None:
    headers = await _root(client, session)
    response = await client.put(
        "/api/admin/settings/openai-key",
        headers=headers,
        json={"api_key": SECRET, "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "secrets_key_missing"
