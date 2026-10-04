from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.users.models import Group, Role, User

DEFAULT_PASSWORD = "correct-horse-42"


async def make_group(session: AsyncSession, name: str = "engineering") -> Group:
    group = Group(name=name, description="")
    session.add(group)
    await session.commit()
    return group


async def make_user(
    session: AsyncSession,
    *,
    username: str = "alice",
    role: Role = Role.USER,
    password: str = DEFAULT_PASSWORD,
    must_change_password: bool = False,
    is_active: bool = True,
    groups: Iterable[Group] = (),
) -> User:
    user = User(
        username=username,
        full_name=username.title(),
        password_hash=hash_password(password),
        role=role.value,
        must_change_password=must_change_password,
        is_active=is_active,
        groups=list(groups),
    )
    session.add(user)
    await session.commit()
    return user
