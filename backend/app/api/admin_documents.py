import asyncio
import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep, SettingsDep, ensure_password_confirmed
from app.core.storage import FileStore
from app.documents import service
from app.documents.access import effective_access_groups
from app.documents.schemas import (
    CollectionCreate,
    CollectionOut,
    CollectionUpdate,
    DocumentGroupsUpdate,
    DocumentOut,
    PasswordConfirm,
    UploadResult,
    VersionOut,
)
from app.ingestion.index import ChunkIndex
from app.users import service as users

router = APIRouter(prefix="/admin", tags=["admin-documents"])

_STATUS: dict[type[Exception], int] = {
    service.NotFound: 404,
    service.CollectionNameTaken: 409,
    service.DuplicateFile: 409,
    service.InvalidState: 409,
    service.RestoreWindowExpired: 409,
    service.InvalidFile: 422,
    service.GroupNotInCollection: 422,
    users.GroupNotFound: 422,
}


def _http_error(exc: service.DocumentServiceError | users.UserServiceError) -> HTTPException:
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


def _index(request: Request) -> ChunkIndex:
    index: ChunkIndex = request.app.state.index
    return index


@router.get("/collections")
async def list_collections(_: AdminUser, session: SessionDep) -> list[CollectionOut]:
    return [CollectionOut.model_validate(c) for c in await service.list_collections(session)]


@router.post("/collections", status_code=201)
async def create_collection(
    body: CollectionCreate, admin: AdminUser, session: SessionDep
) -> CollectionOut:
    try:
        collection = await service.create_collection(
            session,
            actor=admin,
            name=body.name,
            description=body.description,
            group_ids=body.group_ids,
            sensitive=body.sensitive,
        )
    except (service.DocumentServiceError, users.UserServiceError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    return CollectionOut.model_validate(collection)


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: uuid.UUID,
    body: CollectionUpdate,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
) -> CollectionOut:
    if body.group_ids is not None:
        await ensure_password_confirmed(admin, body.password)
    try:
        collection, access_changed = await service.update_collection(
            session,
            actor=admin,
            collection_id=collection_id,
            name=body.name,
            description=body.description,
            group_ids=body.group_ids,
            sensitive=body.sensitive,
        )
    except (service.DocumentServiceError, users.UserServiceError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    if access_changed:
        await service.sync_collection_access(session, _index(request), collection.id)
    return CollectionOut.model_validate(collection)


def _store(request: Request) -> FileStore:
    store: FileStore = request.app.state.store
    return store


def _enqueue(request: Request) -> Callable[[uuid.UUID], None]:
    enqueue: Callable[[uuid.UUID], None] = request.app.state.enqueue
    return enqueue


@router.post("/collections/{collection_id}/documents")
async def upload_documents(
    collection_id: uuid.UUID,
    files: Annotated[list[UploadFile], File()],
    admin: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> list[UploadResult]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    results: list[UploadResult] = []
    queued: list[uuid.UUID] = []
    for upload in files:
        name = upload.filename or ""
        data = await upload.read(max_bytes + 1)
        try:
            document, version = await service.register_upload(
                session,
                actor=admin,
                collection_id=collection_id,
                filename=name,
                data=data,
                max_bytes=max_bytes,
            )
        except service.NotFound as exc:
            raise _http_error(exc) from None
        except service.DuplicateFile as exc:
            results.append(
                UploadResult(
                    filename=name,
                    outcome="duplicate",
                    message=exc.message,
                    document_id=exc.document_id,
                )
            )
            continue
        except service.InvalidFile as exc:
            results.append(UploadResult(filename=name, outcome="invalid", message=exc.message))
            continue
        await asyncio.to_thread(_store(request).save, service.original_key(version.id), data)
        await session.commit()
        queued.append(version.id)
        results.append(
            UploadResult(
                filename=name, outcome="queued", document_id=document.id, version_id=version.id
            )
        )
    for version_id in queued:
        _enqueue(request)(version_id)
    return results


@router.get("/collections/{collection_id}/documents")
async def list_documents(
    collection_id: uuid.UUID,
    _: AdminUser,
    session: SessionDep,
    include_deleted: Annotated[bool, Query()] = False,
) -> list[DocumentOut]:
    documents = await service.list_documents(session, collection_id, include_deleted)
    return [DocumentOut.model_validate(d) for d in documents]


@router.get("/documents/{document_id}")
async def get_document(document_id: uuid.UUID, _: AdminUser, session: SessionDep) -> DocumentOut:
    try:
        return DocumentOut.model_validate(await service.get_document(session, document_id))
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from None


@router.put("/documents/{document_id}/groups")
async def set_document_groups(
    document_id: uuid.UUID,
    body: DocumentGroupsUpdate,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
) -> DocumentOut:
    try:
        document = await service.set_document_groups(
            session, actor=admin, document_id=document_id, group_ids=body.group_ids
        )
    except (service.DocumentServiceError, users.UserServiceError) as exc:
        raise _http_error(exc) from None
    await session.commit()
    await _index(request).set_document_access(document.id, effective_access_groups(document))
    return DocumentOut.model_validate(document)


@router.post("/documents/{document_id}/delete")
async def delete_document(
    document_id: uuid.UUID,
    body: PasswordConfirm,
    admin: AdminUser,
    session: SessionDep,
    request: Request,
) -> DocumentOut:
    await ensure_password_confirmed(admin, body.password)
    try:
        document = await service.soft_delete_document(session, actor=admin, document_id=document_id)
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await _index(request).set_document_deleted(document.id, True)
    return DocumentOut.model_validate(document)


@router.post("/documents/{document_id}/restore")
async def restore_document(
    document_id: uuid.UUID, admin: AdminUser, session: SessionDep, request: Request
) -> DocumentOut:
    try:
        document = await service.restore_document(session, actor=admin, document_id=document_id)
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await _index(request).set_document_deleted(document.id, False)
    return DocumentOut.model_validate(document)


@router.post("/versions/{version_id}/retry")
async def retry_version(
    version_id: uuid.UUID, admin: AdminUser, session: SessionDep, request: Request
) -> VersionOut:
    try:
        version = await service.retry_version(session, actor=admin, version_id=version_id)
    except service.DocumentServiceError as exc:
        raise _http_error(exc) from None
    await session.commit()
    _enqueue(request)(version.id)
    return VersionOut.model_validate(version)


@router.get("/ingestion/status")
async def ingestion_status(_: AdminUser, session: SessionDep) -> dict[str, int]:
    return await service.status_counts(session)
