import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.users.models import User

_ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def create_access_token(user: User, settings: Settings, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "tv": user.token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=settings.jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> tuple[uuid.UUID, int]:
    """Returns (user_id, token_version). Raises TokenError for any invalid token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
        return uuid.UUID(str(payload["sub"])), int(payload["tv"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc
