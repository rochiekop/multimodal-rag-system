"""Login and password change. Functions never commit.
authenticate() records failures before raising, so callers commit on failure too."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.security import (
    WeakPasswordError,
    hash_password,
    hash_password_async,
    validate_password_strength,
    verify_password_async,
)
from app.users.models import User

# Checked when the username doesn't exist, so response time doesn't reveal that.
_DUMMY_HASH = hash_password("timing-equalizer-password-0")


class AuthError(Exception):
    code = "auth_error"


class InvalidCredentials(AuthError):
    code = "invalid_credentials"


class AccountDisabled(AuthError):
    code = "account_disabled"


class AccountLocked(AuthError):
    code = "account_locked"

    def __init__(self, until: datetime) -> None:
        super().__init__(f"Account locked until {until.isoformat()}")
        self.until = until


async def _failed(session: AsyncSession, user: User | None, reason: str, username: str) -> None:
    await audit.record(
        session,
        action="auth.login_failed",
        actor=user,
        target_type="user" if user else None,
        target_id=user.id if user else None,
        detail={"reason": reason, "username": username[:64]},
    )


async def authenticate(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
    now: datetime | None = None,
) -> User:
    now = now or datetime.now(UTC)
    normalized = username.strip().lower()
    # Row lock serialises concurrent attempts for one user so failed-attempt counts aren't lost.
    user = await session.scalar(select(User).where(User.username == normalized).with_for_update())

    if user is None:
        await verify_password_async(_DUMMY_HASH, password)
        await _failed(session, None, "unknown_user", normalized)
        raise InvalidCredentials()

    if user.locked_until is not None and user.locked_until > now:
        await _failed(session, user, "locked", normalized)
        raise AccountLocked(user.locked_until)

    if not await verify_password_async(user.password_hash, password):
        user.failed_login_count += 1
        await _failed(session, user, "bad_password", normalized)
        if user.failed_login_count >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
            user.failed_login_count = 0
            await audit.record(
                session,
                action="auth.account_locked",
                actor=user,
                target_type="user",
                target_id=user.id,
            )
            raise AccountLocked(user.locked_until)
        raise InvalidCredentials()

    if not user.is_active:
        await _failed(session, user, "disabled", normalized)
        raise AccountDisabled()

    user.failed_login_count = 0
    user.locked_until = None
    await audit.record(
        session, action="auth.login_succeeded", actor=user, target_type="user", target_id=user.id
    )
    return user


async def change_password(
    session: AsyncSession, *, user: User, current_password: str, new_password: str
) -> User:
    if not await verify_password_async(user.password_hash, current_password):
        raise InvalidCredentials()
    if new_password == current_password:
        raise WeakPasswordError("New password must differ from the current one")
    validate_password_strength(new_password)

    user.password_hash = await hash_password_async(new_password)
    user.must_change_password = False
    user.token_version += 1  # signs out every other session
    await session.flush()
    await audit.record(
        session, action="auth.password_changed", actor=user, target_type="user", target_id=user.id
    )
    return user
