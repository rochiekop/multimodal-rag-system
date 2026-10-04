import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """Argon2 is CPU- and memory-heavy; run it off the event loop in request paths."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(verify_password, password_hash, password)


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise WeakPasswordError("Password must be at least 12 characters")
    if len(password) > 128:
        raise WeakPasswordError("Password must be at most 128 characters")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise WeakPasswordError("Password must contain at least one letter and a digit")
