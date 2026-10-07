import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.llm import rag_config
from app.llm.rag_config import RagConfig, compute_cost
from app.users.models import Role
from tests.factories import DEFAULT_PASSWORD, bearer, login, make_user

URL = "/api/admin/rag-configs"


async def _root(client: AsyncClient, session: AsyncSession) -> str:
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    return await login(client, "root")


async def test_defaults_apply_until_a_version_is_activated(session: AsyncSession) -> None:
    assert await rag_config.get_active(session) == (None, RagConfig())


async def test_versions_activate_and_roll_back_with_one_active(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _root(client, session)
    first = await client.post(
        URL, headers=bearer(token), json={"config": {"rerank_top_n": 5}, "note": "fewer"}
    )
    second = await client.post(URL, headers=bearer(token), json={"config": {"rerank_top_n": 10}})
    assert first.status_code == 201, first.text
    assert (first.json()["version"], second.json()["version"]) == (1, 2)
    assert first.json()["is_active"] is False

    for created in (first, second, first):  # activate v1, v2, then roll back to v1
        response = await client.post(
            f"{URL}/{created.json()['id']}/activate",
            headers=bearer(token),
            json={"password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is True

    listed = (await client.get(URL, headers=bearer(token))).json()
    assert [v["version"] for v in listed if v["is_active"]] == [1]
    active = (await client.get(f"{URL}/active", headers=bearer(token))).json()
    assert active["version"] == 1
    assert active["config"]["rerank_top_n"] == 5
    actions = (
        await session.scalars(select(AuditLog.action).where(AuditLog.action.like("rag_config.%")))
    ).all()
    assert actions.count("rag_config.created") == 2
    assert actions.count("rag_config.activated") == 3


async def test_activation_requires_password(client: AsyncClient, session: AsyncSession) -> None:
    token = await _root(client, session)
    created = (await client.post(URL, headers=bearer(token), json={"config": {}})).json()
    response = await client.post(
        f"{URL}/{created['id']}/activate", headers=bearer(token), json={"password": "wrong"}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "password_confirmation_failed"
    assert (await rag_config.get_active(session))[0] is None


async def test_admin_cannot_manage_rag_config(client: AsyncClient, session: AsyncSession) -> None:
    await make_user(session, username="boss", role=Role.ADMIN)
    token = await login(client, "boss")
    response = await client.post(URL, headers=bearer(token), json={"config": {}})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "bad", [{"rerank_top_n": 0}, {"unknown_field": 1}, {"reranker_model": "evil/model"}]
)
async def test_invalid_config_is_rejected(
    client: AsyncClient, session: AsyncSession, bad: dict[str, object]
) -> None:
    token = await _root(client, session)
    response = await client.post(URL, headers=bearer(token), json={"config": bad})
    assert response.status_code == 422


def test_compute_cost_uses_configured_prices() -> None:
    cost = compute_cost(RagConfig(), {"gpt-5-mini": (1_000_000, 100_000), "unknown": (5, 5)})
    assert cost == pytest.approx(0.25 + 0.2)
