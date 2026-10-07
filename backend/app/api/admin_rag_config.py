"""RAG configuration versions. super_admin only; activation and rollback need password
re-entry and are audited (spec §4.2)."""

import uuid

from fastapi import APIRouter

from app.api.errors import api_error
from app.auth.deps import SessionDep, SuperAdminUser, ensure_password_confirmed
from app.documents.schemas import PasswordConfirm
from app.llm import rag_config as service
from app.llm.rag_config import ActiveConfigOut, RagConfigCreate, RagConfigVersionOut

router = APIRouter(prefix="/admin/rag-configs", tags=["admin-rag-config"])


@router.get("")
async def list_versions(_: SuperAdminUser, session: SessionDep) -> list[RagConfigVersionOut]:
    return [RagConfigVersionOut.model_validate(r) for r in await service.list_versions(session)]


@router.get("/active")
async def get_active(_: SuperAdminUser, session: SessionDep) -> ActiveConfigOut:
    version, config = await service.get_active(session)
    return ActiveConfigOut(version=version, config=config)


@router.post("", status_code=201)
async def create_version(
    body: RagConfigCreate, user: SuperAdminUser, session: SessionDep
) -> RagConfigVersionOut:
    row = await service.create_version(session, user, body.config, body.note)
    await session.commit()
    return RagConfigVersionOut.model_validate(row)


@router.post("/{config_id}/activate")
async def activate(
    config_id: uuid.UUID, body: PasswordConfirm, user: SuperAdminUser, session: SessionDep
) -> RagConfigVersionOut:
    await ensure_password_confirmed(user, body.password)
    try:
        row = await service.activate(session, user, config_id)
    except service.RagConfigNotFound as exc:
        raise api_error(404, exc.code, exc.message) from None
    await session.commit()
    return RagConfigVersionOut.model_validate(row)
