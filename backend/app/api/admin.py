import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.errors import api_error
from app.audit import service as audit
from app.audit.schemas import AuditEntryOut
from app.auth.deps import AdminUser, SessionDep
from app.core.security import WeakPasswordError
from app.users import service
from app.users.schemas import (
    GroupCreate,
    GroupOut,
    PasswordReset,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_STATUS: dict[type[service.UserServiceError], int] = {
    service.NotFound: 404,
    service.UsernameTaken: 409,
    service.GroupNameTaken: 409,
    service.InvalidUsername: 422,
    service.GroupNotFound: 422,
    service.PermissionDenied: 403,
}


def _http_error(exc: service.UserServiceError | WeakPasswordError) -> HTTPException:
    if isinstance(exc, WeakPasswordError):
        return api_error(422, "weak_password", str(exc))
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


@router.get("/users")
async def list_users(_: AdminUser, session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await service.list_users(session)]


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, admin: AdminUser, session: SessionDep) -> UserOut:
    try:
        user = await service.create_user(
            session,
            actor=admin,
            username=body.username,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
            group_ids=body.group_ids,
        )
    except (service.UserServiceError, WeakPasswordError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.update_user(
            session,
            actor=admin,
            user_id=user_id,
            full_name=body.full_name,
            role=body.role,
            group_ids=body.group_ids,
            is_active=body.is_active,
            unlock=body.unlock,
        )
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID, body: PasswordReset, admin: AdminUser, session: SessionDep
) -> UserOut:
    try:
        user = await service.reset_password(
            session, actor=admin, user_id=user_id, new_password=body.new_password
        )
    except (service.UserServiceError, WeakPasswordError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    return UserOut.model_validate(user)


@router.get("/groups")
async def list_groups(_: AdminUser, session: SessionDep) -> list[GroupOut]:
    return [GroupOut.model_validate(g) for g in await service.list_groups(session)]


@router.post("/groups", status_code=201)
async def create_group(body: GroupCreate, admin: AdminUser, session: SessionDep) -> GroupOut:
    try:
        group = await service.create_group(
            session, actor=admin, name=body.name, description=body.description
        )
    except service.UserServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return GroupOut.model_validate(group)


@router.get("/audit")
async def list_audit(
    _: AdminUser, session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[AuditEntryOut]:
    return [AuditEntryOut.model_validate(e) for e in await audit.list_recent(session, limit)]
