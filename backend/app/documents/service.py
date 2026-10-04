"""Collections and documents use cases. Functions flush but never commit; callers commit."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.documents.access import effective_access_groups
from app.documents.models import Collection, Document
from app.ingestion.index import ChunkIndex
from app.users.models import User
from app.users.service import load_groups


class DocumentServiceError(Exception):
    code = "document_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DocumentServiceError):
    code = "not_found"


class CollectionNameTaken(DocumentServiceError):
    code = "collection_name_taken"


class InvalidFile(DocumentServiceError):
    code = "invalid_file"


class DuplicateFile(DocumentServiceError):
    code = "duplicate_file"

    def __init__(self, message: str, document_id: uuid.UUID) -> None:
        super().__init__(message)
        self.document_id = document_id


class InvalidState(DocumentServiceError):
    code = "invalid_state"


class GroupNotInCollection(DocumentServiceError):
    code = "group_not_in_collection"


class RestoreWindowExpired(DocumentServiceError):
    code = "restore_window_expired"


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude_id: uuid.UUID | None = None
) -> None:
    query = select(Collection.id).where(Collection.name == name)
    if exclude_id is not None:
        query = query.where(Collection.id != exclude_id)
    if await session.scalar(query) is not None:
        raise CollectionNameTaken(f"Collection '{name}' already exists")


async def get_collection(session: AsyncSession, collection_id: uuid.UUID) -> Collection:
    collection = await session.get(Collection, collection_id)
    if collection is None:
        raise NotFound("Collection not found")
    return collection


async def create_collection(
    session: AsyncSession,
    *,
    actor: User,
    name: str,
    description: str = "",
    group_ids: Iterable[uuid.UUID] = (),
    sensitive: bool = False,
) -> Collection:
    clean = name.strip()
    await _ensure_name_free(session, clean)
    collection = Collection(
        name=clean,
        description=description.strip(),
        sensitive=sensitive,
        groups=await load_groups(session, group_ids),
    )
    session.add(collection)
    await session.flush()
    await audit.record(
        session,
        action="collection.created",
        actor=actor,
        target_type="collection",
        target_id=collection.id,
        detail={"name": clean, "group_ids": [str(g.id) for g in collection.groups]},
    )
    return collection


async def update_collection(
    session: AsyncSession,
    *,
    actor: User,
    collection_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    group_ids: Iterable[uuid.UUID] | None = None,
    sensitive: bool | None = None,
) -> tuple[Collection, bool]:
    """Returns (collection, access_changed)."""
    collection = await get_collection(session, collection_id)
    changes: dict[str, object] = {}
    access_changed = False
    if name is not None:
        clean = name.strip()
        await _ensure_name_free(session, clean, exclude_id=collection.id)
        collection.name = clean
        changes["name"] = clean
    if description is not None:
        collection.description = description.strip()
        changes["description"] = collection.description
    if sensitive is not None:
        collection.sensitive = sensitive
        changes["sensitive"] = sensitive
    if group_ids is not None:
        new_groups = await load_groups(session, group_ids)
        access_changed = {g.id for g in new_groups} != {g.id for g in collection.groups}
        collection.groups = new_groups
        changes["group_ids"] = [str(g.id) for g in new_groups]
    await session.flush()
    await audit.record(
        session,
        action="collection.updated",
        actor=actor,
        target_type="collection",
        target_id=collection.id,
        detail=changes,
    )
    return collection, access_changed


async def list_collections(session: AsyncSession) -> list[Collection]:
    return list((await session.scalars(select(Collection).order_by(Collection.name))).all())


async def sync_collection_access(
    session: AsyncSession, index: ChunkIndex, collection_id: uuid.UUID
) -> None:
    """Push every document's effective access to its chunks (no re-embedding)."""
    documents = await session.scalars(
        select(Document).where(Document.collection_id == collection_id)
    )
    for document in documents:
        await index.set_document_access(document.id, effective_access_groups(document))
