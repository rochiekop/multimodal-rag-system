from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.schemas import AuditFilters
from app.core.logging import request_id_var

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
        request_id=request_id_var.get(),
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_recent(session: AsyncSession, limit: int = 100) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())


CSV_COLUMNS = [
    "id",
    "created_at",
    "actor_username",
    "actor_id",
    "action",
    "target_type",
    "target_id",
    "request_id",
    "detail",
]
MAX_EXPORT_ROWS = 100_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _filtered(filters: AuditFilters) -> Select[AuditLog]:
    query = select(AuditLog)
    if filters.actor:
        query = query.where(func.lower(AuditLog.actor_username) == filters.actor.strip().lower())
    if filters.action:
        query = query.where(AuditLog.action.startswith(filters.action.strip(), autoescape=True))
    if filters.target_type:
        query = query.where(AuditLog.target_type == filters.target_type)
    if filters.target_id:
        query = query.where(AuditLog.target_id == filters.target_id)
    if filters.since:
        query = query.where(AuditLog.created_at >= filters.since)
    if filters.until:
        query = query.where(AuditLog.created_at < filters.until)
    return query


async def search(
    session: AsyncSession, filters: AuditFilters, *, before_id: int | None, limit: int
) -> list[AuditLog]:
    query = _filtered(filters)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    query = query.order_by(AuditLog.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


def csv_line(values: Sequence[object]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerow([_cell(v) for v in values])
    return buffer.getvalue()


async def export_lines(session: AsyncSession, filters: AuditFilters) -> AsyncIterator[str]:
    """CSV lines (header first), newest first, at most MAX_EXPORT_ROWS rows."""
    yield csv_line(CSV_COLUMNS)
    query = _filtered(filters).order_by(AuditLog.id.desc()).limit(MAX_EXPORT_ROWS)
    rows = await session.stream_scalars(query.execution_options(yield_per=1000))
    async for entry in rows:
        yield csv_line(
            [
                entry.id,
                entry.created_at.isoformat(),
                entry.actor_username,
                entry.actor_id,
                entry.action,
                entry.target_type,
                entry.target_id,
                entry.request_id,
                json.dumps(entry.detail, sort_keys=True, default=str),
            ]
        )
