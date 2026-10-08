"""Admin dashboard (spec §6.5): usage, quality and ingestion figures plus service health."""

import asyncio
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.dashboard import service
from app.documents import service as documents

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])
PERIODS = (7, 30, 90)


class DashboardOut(BaseModel):
    days: int
    totals: service.Totals
    daily: list[service.DailyPoint]
    ingestion: dict[str, int]
    health: dict[str, str]


async def _probe(check: Awaitable[Any]) -> str:
    try:
        async with asyncio.timeout(2):
            await check
    except Exception:
        return "error"
    return "ok"


@router.get("")
async def get_dashboard(
    _: AdminUser, session: SessionDep, request: Request, days: int = 30
) -> DashboardOut:
    if days not in PERIODS:
        raise api_error(422, "invalid_days", "days must be 7, 30 or 90")
    totals, daily = await service.summary(session, days)
    health = {
        "database": "ok",  # the queries above succeeded
        "qdrant": await _probe(request.app.state.index.client.get_collections()),
        "redis": await _probe(request.app.state.rate_limiter.redis.ping()),
    }
    return DashboardOut(
        days=days,
        totals=totals,
        daily=daily,
        ingestion=await documents.status_counts(session),
        health=health,
    )
