from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog

if TYPE_CHECKING:
    from app.users.models import User


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit entry to the caller's transaction. The caller commits."""
    entry = AuditLog(
        actor_id=actor.id if actor is not None else None,
        actor_username=actor.username if actor is not None else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail or {},
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_recent(session: AsyncSession, limit: int = 100) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())
