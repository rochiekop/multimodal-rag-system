import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.users.models import Role


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    full_name: str
    role: Role
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    groups: list[GroupOut]
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=128)
    role: Role = Role.USER
    group_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    group_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None
    unlock: bool = False


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
