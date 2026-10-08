import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.llm import rag_config
from app.llm.rag_config import RagConfig, compute_cost, price_key
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


def test_cost_caps_require_a_price_for_every_model() -> None:
    with pytest.raises(ValidationError) as caught:
        RagConfig.model_validate({"chat_model": "mystery", "fallback_model": "backup"})
    assert "backup, mystery" in str(caught.value)
    uncapped = {"user_daily_cost_usd": 0, "installation_daily_cost_usd": 0}
    assert RagConfig.model_validate({"chat_model": "mystery", "guardrails": uncapped})
    priced = RagConfig.model_validate(
        {
            "chat_model": "mystery",
            "prices": {
                **RagConfig().model_dump()["prices"],
                "mystery": {"input_per_mtok": 1, "output_per_mtok": 1},
            },
        }
    )
    assert priced.chat_model == "mystery"


async def test_unpriced_model_with_caps_is_rejected_by_the_api(
    client: AsyncClient, session: AsyncSession
) -> None:
    token = await _root(client, session)
    response = await client.post(
        URL, headers=bearer(token), json={"config": {"guardrails": {"judge_model": "mystery"}}}
    )
    assert response.status_code == 422
    assert "mystery" in response.text


def test_price_key_follows_the_reported_model() -> None:
    config = RagConfig.model_validate(
        {
            "prices": {
                **RagConfig().model_dump()["prices"],
                "gpt-5": {"input_per_mtok": 1, "output_per_mtok": 1},
            }
        }
    )
    assert price_key(config, "gpt-5-mini", None) == "gpt-5-mini"
    assert price_key(config, "gpt-5-mini", {"model_name": "gpt-5-nano"}) == "gpt-5-nano"
    assert price_key(config, "gpt-5", {"model_name": "gpt-5-mini-2025-08-07"}) == "gpt-5-mini"
    assert price_key(config, "gpt-5-mini", {"model": "gpt-5-2025-08-07"}) == "gpt-5"
    assert price_key(config, "gpt-5-mini", {"model_name": "other"}) == "gpt-5-mini"
