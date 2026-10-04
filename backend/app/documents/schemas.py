import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.users.schemas import GroupOut


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    sensitive: bool = False


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    group_ids: list[uuid.UUID] | None = None
    sensitive: bool | None = None
    password: str | None = Field(default=None, max_length=128)


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    sensitive: bool
    groups: list[GroupOut]
    created_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_no: int
    status: str
    failed_stage: str | None
    error: str | None
    chunk_count: int
    page_count: int | None
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    filename: str
    current_version_id: uuid.UUID | None
    deleted_at: datetime | None
    restricted_groups: list[GroupOut]
    versions: list[VersionOut]
    created_at: datetime


class UploadResult(BaseModel):
    filename: str
    outcome: Literal["queued", "duplicate", "invalid"]
    message: str = ""
    document_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None


class DocumentGroupsUpdate(BaseModel):
    group_ids: list[uuid.UUID]


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ChunkOut(BaseModel):
    position: int
    text: str
    modality: str
    page: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
