import uuid

from fastapi import APIRouter, HTTPException, Request

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep, ensure_password_confirmed
from app.documents import service
from app.documents.schemas import CollectionCreate, CollectionOut, CollectionUpdate
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
