"""Operator commands. Usage: python -m app.cli create-superadmin --username NAME --full-name NAME"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.security import WeakPasswordError
from app.users.models import Role, User
from app.users.service import UserServiceError, create_user


async def create_superadmin(
    sessionmaker: async_sessionmaker[AsyncSession], *, username: str, full_name: str, password: str
) -> User:
    async with sessionmaker() as session:
        user = await create_user(
            session,
            actor=None,
            username=username,
            full_name=full_name,
            password=password,
            role=Role.SUPER_ADMIN,
            must_change_password=False,
        )
        await session.commit()
        return user


def _read_password() -> str:
    from_env = os.environ.get("RAG_SUPERADMIN_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise WeakPasswordError("Passwords do not match")
    return first


async def _run(username: str, full_name: str, password: str) -> User:
    engine = create_engine(get_settings().database_url)
    try:
        return await create_superadmin(
            create_sessionmaker(engine), username=username, full_name=full_name, password=password
        )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-superadmin", help="Create the first super admin")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    args = parser.parse_args(argv)

    try:
        user = asyncio.run(_run(args.username, args.full_name, _read_password()))
    except (UserServiceError, WeakPasswordError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created super admin '{user.username}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
