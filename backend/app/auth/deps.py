from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import api_error
from app.auth.service import InvalidCredentials, confirm_password
from app.auth.tokens import TokenError, decode_access_token
from app.core.config import Settings, get_app_settings
from app.core.db import get_session
from app.users.models import ROLE_RANK, Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]

_bearer = HTTPBearer(auto_error=False)
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


async def current_user_allow_password_change(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Any authenticated, active user, including one who still must change their password."""
    if credentials is None:
        raise api_error(401, "not_authenticated", "Missing bearer token", headers=_WWW_AUTH)
    try:
        user_id, token_version = decode_access_token(credentials.credentials, settings)
    except TokenError:
        raise api_error(
            401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH
        ) from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise api_error(401, "invalid_token", "Invalid or expired token", headers=_WWW_AUTH)
    return user


async def current_user(
    user: Annotated[User, Depends(current_user_allow_password_change)],
) -> User:
    if user.must_change_password:
        raise api_error(403, "password_change_required", "You must change your password first")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _ensure_role(user: User, minimum: Role) -> User:
    if ROLE_RANK[Role(user.role)] < ROLE_RANK[minimum]:
        raise api_error(403, "forbidden", "Your role does not allow this action")
    return user


async def require_admin(user: CurrentUser) -> User:
    return _ensure_role(user, Role.ADMIN)


async def require_super_admin(user: CurrentUser) -> User:
    return _ensure_role(user, Role.SUPER_ADMIN)


AdminUser = Annotated[User, Depends(require_admin)]


async def ensure_password_confirmed(user: User, password: str | None) -> None:
    try:
        await confirm_password(user, password)
    except InvalidCredentials:
        raise api_error(
            403, "password_confirmation_failed", "Re-enter your password to confirm"
        ) from None


SuperAdminUser = Annotated[User, Depends(require_super_admin)]
