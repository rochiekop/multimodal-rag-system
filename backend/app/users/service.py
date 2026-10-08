"""User and group management use cases. Functions flush but never commit; callers commit."""

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.security import hash_password_async, validate_password_strength
from app.users.models import Group, Role, User

_USERNAME_RE = re.compile(r"[a-z0-9._-]{3,64}")


class UserServiceError(Exception):
    code = "user_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(UserServiceError):
    code = "not_found"


class UsernameTaken(UserServiceError):
    code = "username_taken"


class InvalidUsername(UserServiceError):
    code = "invalid_username"


class GroupNotFound(UserServiceError):
    code = "group_not_found"


class GroupNameTaken(UserServiceError):
    code = "group_name_taken"


class PermissionDenied(UserServiceError):
    code = "forbidden"


def _normalize_username(raw: str) -> str:
    username = raw.strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise InvalidUsername(
            "Username must be 3-64 characters using letters, digits, '.', '_' or '-'"
        )
    return username


def _ensure_can_manage(actor: User | None, target_role: Role) -> None:
    """super_admin manages everyone; admin manages only regular users; None is the system."""
    if actor is None or actor.role == Role.SUPER_ADMIN:
        return
    if actor.role == Role.ADMIN and target_role is Role.USER:
        return
    raise PermissionDenied(f"Your role cannot manage {target_role.value} accounts")


async def _get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def load_groups(session: AsyncSession, group_ids: Iterable[uuid.UUID]) -> list[Group]:
    wanted = list(dict.fromkeys(group_ids))
    if not wanted:
        return []
    groups = list((await session.scalars(select(Group).where(Group.id.in_(wanted)))).all())
    if len(groups) != len(wanted):
        raise GroupNotFound("One or more groups do not exist")
    return sorted(groups, key=lambda g: g.name)


async def create_user(
    session: AsyncSession,
    *,
    actor: User | None,
    username: str,
    full_name: str,
    password: str,
    role: Role = Role.USER,
    group_ids: Iterable[uuid.UUID] = (),
    must_change_password: bool = True,
) -> User:
    _ensure_can_manage(actor, role)
    normalized = _normalize_username(username)
    validate_password_strength(password)
    if await session.scalar(select(User.id).where(User.username == normalized)) is not None:
        raise UsernameTaken(f"Username '{normalized}' is already taken")

    user = User(
        username=normalized,
        full_name=full_name.strip(),
        password_hash=await hash_password_async(password),
        role=role.value,
        must_change_password=must_change_password,
        groups=await load_groups(session, group_ids),
    )
    session.add(user)
    await session.flush()
    await audit.record(
        session,
        action="user.created",
        actor=actor,
        target_type="user",
        target_id=user.id,
        detail={"username": normalized, "role": role.value},
    )
    return user


async def update_user(
    session: AsyncSession,
    *,
    actor: User,
    user_id: uuid.UUID,
    full_name: str | None = None,
    role: Role | None = None,
    group_ids: Iterable[uuid.UUID] | None = None,
    is_active: bool | None = None,
    unlock: bool = False,
) -> User:
    user = await _get_user(session, user_id)
    _ensure_can_manage(actor, Role(user.role))
    changes: dict[str, object] = {}

    if full_name is not None:
        user.full_name = full_name.strip()
        changes["full_name"] = user.full_name
    if role is not None and role.value != user.role:
        if user.id == actor.id:
            raise PermissionDenied("You cannot change your own role")
        _ensure_can_manage(actor, role)
        user.role = role.value
        user.token_version += 1
        changes["role"] = role.value
    if group_ids is not None:
        user.groups = await load_groups(session, group_ids)
        changes["group_ids"] = [str(g.id) for g in user.groups]
    if is_active is not None and is_active != user.is_active:
        if not is_active and user.id == actor.id:
            raise PermissionDenied("You cannot deactivate yourself")
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
        changes["is_active"] = is_active
    if unlock:
        user.locked_until = None
        user.failed_login_count = 0
        user.chat_locked_until = None
        user.strike_reset_at = datetime.now(UTC)
        changes["unlocked"] = True

    await session.flush()
    await audit.record(
        session,
        action="user.updated",
        actor=actor,
        target_type="user",
        target_id=user.id,
        detail=changes,
    )
    return user


async def reset_password(
    session: AsyncSession, *, actor: User, user_id: uuid.UUID, new_password: str
) -> User:
    user = await _get_user(session, user_id)
    _ensure_can_manage(actor, Role(user.role))
    validate_password_strength(new_password)
    user.password_hash = await hash_password_async(new_password)
    user.must_change_password = True
    user.token_version += 1
    await session.flush()
    await audit.record(
        session, action="user.password_reset", actor=actor, target_type="user", target_id=user.id
    )
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def create_group(
    session: AsyncSession, *, actor: User | None, name: str, description: str = ""
) -> Group:
    clean_name = name.strip()
    if await session.scalar(select(Group.id).where(Group.name == clean_name)) is not None:
        raise GroupNameTaken(f"Group '{clean_name}' already exists")
    group = Group(name=clean_name, description=description.strip())
    session.add(group)
    await session.flush()
    await audit.record(
        session,
        action="group.created",
        actor=actor,
        target_type="group",
        target_id=group.id,
        detail={"name": clean_name},
    )
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.scalars(select(Group).order_by(Group.name))).all())
