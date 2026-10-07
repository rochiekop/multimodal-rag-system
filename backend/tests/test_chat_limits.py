from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.models import Conversation
from app.guardrails.limits import RateLimiter
from app.guardrails.models import Notification, UsageRecord
from tests.factories import (
    activate_config,
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
    seed_document,
)


async def _world(app: FastAPI, client: AsyncClient, session: AsyncSession):
    hr = await make_group(session, "hr")
    alice = await make_user(session, username="alice", groups=[hr])
    coll = await make_collection(session, "HR", [hr])
    await seed_document(session, app.state.index, coll, ["Annual leave is 25 days."])
    app.state.chat_deps = chat_deps(app.state.index)
    return alice, await login(client, "alice")


async def _ask(client: AsyncClient, token: str, question: str = "How many leave days?"):
    return await client.post("/api/chat", headers=bearer(token), json={"question": question})


async def test_locked_user_gets_423_without_creating_a_conversation(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    alice, token = await _world(app, client, session)
    alice.chat_locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()
    response = await _ask(client, token)
    assert response.status_code == 423
    assert response.json()["detail"]["code"] == "chat_locked"
    assert await session.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_rate_limit_per_minute(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, token = await _world(app, client, session)
    await activate_config(session, guardrails={"rate_limit_per_minute": 2})
    assert (await _ask(client, token)).status_code == 200
    assert (await _ask(client, token)).status_code == 200
    third = await _ask(client, token)
    assert third.status_code == 429 and third.json()["detail"]["code"] == "rate_limited"


async def test_question_length_limit(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    _, token = await _world(app, client, session)
    await activate_config(session, guardrails={"max_question_chars": 20})
    response = await _ask(client, token, "x" * 21)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "question_too_long"


async def test_user_and_installation_daily_caps(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    alice, token = await _world(app, client, session)
    bob = await make_user(session, username="bob")
    session.add(UsageRecord(user_id=bob.id, cost_usd=50.0))
    await session.commit()
    installation = await _ask(client, token)
    assert installation.status_code == 429
    assert installation.json()["detail"]["code"] == "service_limit_reached"

    await activate_config(session, guardrails={"installation_daily_cost_usd": 0})  # no cap
    session.add(UsageRecord(user_id=alice.id, cost_usd=2.5))
    await session.commit()
    personal = await _ask(client, token)
    assert personal.status_code == 429
    assert personal.json()["detail"]["code"] == "daily_limit_reached"


async def test_cost_alert_notifies_admins_once_per_day(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    alice, token = await _world(app, client, session)
    session.add(UsageRecord(user_id=alice.id, cost_usd=1.7))  # 85% of the $2 default
    await session.commit()
    assert (await _ask(client, token)).status_code == 200
    assert (await _ask(client, token)).status_code == 200
    kinds = (await session.scalars(select(Notification.kind))).all()
    assert kinds == ["cost_alert"]


async def test_rate_limiter_fails_open_when_redis_is_down() -> None:
    limiter = RateLimiter(Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2))
    assert await limiter.hit("user:x", limit=1) is True
    await limiter.redis.aclose()
