"""In-app admin notifications (strike locks, cost-cap alerts)."""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.guardrails import service

router = APIRouter(prefix="/admin/notifications", tags=["admin-notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    target_type: str | None
    target_id: str | None
    created_at: datetime
    read_at: datetime | None


@router.get("")
async def list_notifications(
    _: AdminUser, session: SessionDep, unread: bool = False
) -> list[NotificationOut]:
    notes = await service.list_notifications(session, unread_only=unread)
    return [NotificationOut.model_validate(n) for n in notes]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID, _: AdminUser, session: SessionDep
) -> NotificationOut:
    try:
        note = await service.mark_read(session, notification_id)
    except service.NotificationNotFound as exc:
        raise api_error(404, exc.code, exc.message) from None
    await session.commit()
    return NotificationOut.model_validate(note)
