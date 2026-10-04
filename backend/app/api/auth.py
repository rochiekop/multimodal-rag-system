from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.errors import api_error
from app.auth.deps import SessionDep, SettingsDep, current_user_allow_password_change
from app.auth.service import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    authenticate,
    change_password,
)
from app.auth.tokens import create_access_token
from app.core.config import Settings
from app.core.security import WeakPasswordError
from app.users.models import User
from app.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

PendingUser = Annotated[User, Depends(current_user_allow_password_change)]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    must_change_password: bool
    user: UserOut


def _token_response(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user, settings),
        expires_in=settings.jwt_ttl_seconds,
        must_change_password=user.must_change_password,
        user=UserOut.model_validate(user),
    )


@router.post("/login")
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    try:
        user = await authenticate(
            session, username=body.username, password=body.password, settings=settings
        )
    except AccountLocked as exc:
        await session.commit()  # persist the lock and the audit entries
        raise api_error(
            423, exc.code, "Account is temporarily locked", locked_until=exc.until.isoformat()
        ) from None
    except AccountDisabled as exc:
        await session.commit()
        raise api_error(403, exc.code, "Account is disabled") from None
    except InvalidCredentials as exc:
        await session.commit()
        raise api_error(401, exc.code, "Invalid username or password") from None
    await session.commit()
    return _token_response(user, settings)


@router.get("/me")
async def me(user: PendingUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password")
async def change_password_route(
    body: ChangePasswordRequest, user: PendingUser, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    try:
        await change_password(
            session,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except InvalidCredentials as exc:
        raise api_error(400, exc.code, "Current password is incorrect") from None
    except WeakPasswordError as exc:
        raise api_error(422, "weak_password", str(exc)) from None
    await session.commit()
    return _token_response(user, settings)
