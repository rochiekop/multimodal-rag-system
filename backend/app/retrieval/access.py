"""Who may read what, decided from Postgres (the source of truth), never from the client."""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.access import effective_access_groups
from app.documents.models import Collection, Document, collection_groups
from app.users.models import User


def _group_ids(user: User) -> set[uuid.UUID]:
    return {g.id for g in user.groups}


async def visible_collections(session: AsyncSession, user: User) -> list[Collection]:
    group_ids = _group_ids(user)
    if not group_ids:
        return []
    visible = (
        select(collection_groups.c.collection_id)
        .where(collection_groups.c.group_id.in_(group_ids))
        .distinct()
    )
    query = select(Collection).where(Collection.id.in_(visible)).order_by(Collection.name)
    return list((await session.scalars(query)).all())


async def visible_collection_ids(
    session: AsyncSession, user: User, requested: Sequence[uuid.UUID] = ()
) -> list[uuid.UUID]:
    """Collections the user can see; when some are requested, only those among them."""
    ids = [c.id for c in await visible_collections(session, user)]
    if requested:
        wanted = set(requested)
        ids = [i for i in ids if i in wanted]
    return ids


async def permitted_documents(
    session: AsyncSession, user: User, doc_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Document]:
    """Live (not deleted, indexed) documents among doc_ids that the user may read."""
    wanted = set(doc_ids)
    if not wanted:
        return {}
    user_groups = {str(g) for g in _group_ids(user)}
    query = select(Document).where(
        Document.id.in_(wanted),
        Document.deleted_at.is_(None),
        Document.current_version_id.is_not(None),
    )
    return {
        d.id: d
        for d in (await session.scalars(query)).all()
        if user_groups & set(effective_access_groups(d))
    }
