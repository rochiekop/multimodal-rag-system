"""Collections and documents use cases. Functions flush but never commit; callers commit."""

import hashlib
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.documents import filetypes
from app.documents.access import effective_access_groups
from app.documents.models import Collection, Document, DocumentStatus, DocumentVersion
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


RESTORE_WINDOW = timedelta(days=30)


def original_key(version_id: uuid.UUID) -> str:
    return f"versions/{version_id}/original"


async def register_upload(
    session: AsyncSession,
    *,
    actor: User,
    collection_id: uuid.UUID,
    filename: str,
    data: bytes,
    max_bytes: int,
) -> tuple[Document, DocumentVersion]:
    collection = await get_collection(session, collection_id)
    try:
        clean_name = filetypes.sanitize_filename(filename)
        if len(data) > max_bytes:
            raise filetypes.FileTypeError(f"File exceeds {max_bytes // (1024 * 1024)} MB")
        kind = filetypes.detect_kind(clean_name, data)
    except filetypes.FileTypeError as exc:
        raise InvalidFile(str(exc)) from None

    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(DocumentVersion.document_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.sha256 == digest,
            Document.deleted_at.is_(None),
            DocumentVersion.status != DocumentStatus.REJECTED.value,
        )
        .limit(1)
    )
    if existing is not None:
        raise DuplicateFile("Identical content was already uploaded", existing)

    document = await session.scalar(
        select(Document).where(
            Document.collection_id == collection.id, Document.filename == clean_name
        )
    )
    if document is None:
        document = Document(
            collection=collection, filename=clean_name, versions=[], restricted_groups=[]
        )
        session.add(document)
    elif document.deleted_at is not None:
        raise InvalidFile("A deleted document with this name exists; restore it first")

    version = DocumentVersion(
        version_no=max((v.version_no for v in document.versions), default=0) + 1,
        sha256=digest,
        content_type=filetypes.CONTENT_TYPES[kind],
        size_bytes=len(data),
        status=DocumentStatus.QUEUED.value,
        uploaded_by=actor.id,
    )
    document.versions.append(version)
    await session.flush()
    await audit.record(
        session,
        action="document.uploaded",
        actor=actor,
        target_type="document",
        target_id=document.id,
        detail={"filename": clean_name, "version": version.version_no, "size": len(data)},
    )
    return document, version


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFound("Document not found")
    return document


async def list_documents(
    session: AsyncSession, collection_id: uuid.UUID, include_deleted: bool = False
) -> list[Document]:
    query = select(Document).where(Document.collection_id == collection_id)
    if not include_deleted:
        query = query.where(Document.deleted_at.is_(None))
    return list((await session.scalars(query.order_by(Document.filename))).all())


async def set_document_groups(
    session: AsyncSession, *, actor: User, document_id: uuid.UUID, group_ids: Iterable[uuid.UUID]
) -> Document:
    document = await get_document(session, document_id)
    groups = await load_groups(session, group_ids)
    allowed = {g.id for g in document.collection.groups}
    if any(g.id not in allowed for g in groups):
        raise GroupNotInCollection("A document can only be restricted to its collection's groups")
    document.restricted_groups = groups
    await session.flush()
    await audit.record(
        session,
        action="document.groups_changed",
        actor=actor,
        target_type="document",
        target_id=document.id,
        detail={"group_ids": [str(g.id) for g in groups]},
    )
    return document


async def soft_delete_document(
    session: AsyncSession, *, actor: User, document_id: uuid.UUID
) -> Document:
    document = await get_document(session, document_id)
    if document.deleted_at is None:
        document.deleted_at = datetime.now(UTC)
        await session.flush()
        await audit.record(
            session,
            action="document.deleted",
            actor=actor,
            target_type="document",
            target_id=document.id,
        )
    return document


async def restore_document(
    session: AsyncSession, *, actor: User, document_id: uuid.UUID, now: datetime | None = None
) -> Document:
    document = await get_document(session, document_id)
    if document.deleted_at is None:
        return document
    if (now or datetime.now(UTC)) - document.deleted_at > RESTORE_WINDOW:
        raise RestoreWindowExpired("Documents can only be restored within 30 days")
    document.deleted_at = None
    await session.flush()
    await audit.record(
        session,
        action="document.restored",
        actor=actor,
        target_type="document",
        target_id=document.id,
    )
    return document


STUCK_AFTER = timedelta(minutes=30)
_IN_FLIGHT = {
    DocumentStatus.SCANNING.value,
    DocumentStatus.PARSING.value,
    DocumentStatus.ENRICHING.value,
    DocumentStatus.CHUNKING.value,
    DocumentStatus.EMBEDDING.value,
    DocumentStatus.INDEXING.value,
}


async def retry_version(
    session: AsyncSession,
    *,
    actor: User,
    version_id: uuid.UUID,
    now: datetime | None = None,
) -> DocumentVersion:
    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise NotFound("Version not found")
    current = now or datetime.now(UTC)
    stuck = version.status in _IN_FLIGHT and current - version.updated_at > STUCK_AFTER
    if version.status != DocumentStatus.FAILED.value and not stuck:
        raise InvalidState("Only failed or stuck versions can be retried")
    version.status = DocumentStatus.QUEUED.value
    version.error = None
    version.failed_stage = None
    await session.flush()
    await audit.record(
        session,
        action="document.retry",
        actor=actor,
        target_type="document",
        target_id=version.document_id,
        detail={"version": version.version_no},
    )
    return version


async def status_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(DocumentVersion.status, func.count()).group_by(DocumentVersion.status)
    )
    counts = {status.value: 0 for status in DocumentStatus}
    counts.update({status: count for status, count in rows.all()})
    return counts
