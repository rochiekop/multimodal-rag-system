import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_username: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any]
    request_id: str | None = None


class AuditFilters(BaseModel):
    actor: str | None = Field(default=None, max_length=64)  # username, case-insensitive
    action: str | None = Field(default=None, max_length=100)  # prefix, e.g. "user."
    target_type: str | None = Field(default=None, max_length=50)
    target_id: str | None = Field(default=None, max_length=100)
    since: datetime | None = None
    until: datetime | None = None
