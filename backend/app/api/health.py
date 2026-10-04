import asyncio

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    database = "ok"
    try:
        async with asyncio.timeout(3):
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        database = "error"

    healthy = database == "ok"
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "database": database}
