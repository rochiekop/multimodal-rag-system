"""Browser sessions: the JWT lives in an httpOnly cookie that page scripts can't read.
Cookie-authenticated writes must carry a custom header, which a cross-site page can't send
without CORS (the API enables none)."""

from fastapi import Response

from app.core.config import Settings

SESSION_COOKIE = "rag_session"
CSRF_HEADER = "X-CSRF-Protection"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure(),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.cookie_secure(),
        samesite="strict",
        path="/",
    )
