"""RAG configuration versions. super_admin only; activation and rollback need password
re-entry and are audited (spec §4.2)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.errors import api_error
from app.auth.deps import SessionDep, SuperAdminUser, ensure_password_confirmed
from app.documents.schemas import PasswordConfirm
from app.evaluation import runs as eval_runs
from app.llm import rag_config as service
from app.llm.models import RagConfigVersion
from app.llm.rag_config import ActiveConfigOut, RagConfigCreate, RagConfigVersionOut

router = APIRouter(prefix="/admin/rag-configs", tags=["admin-rag-config"])


@router.get("")
async def list_versions(_: SuperAdminUser, session: SessionDep) -> list[RagConfigVersionOut]:
    rows = await service.list_versions(session)
    latest = await eval_runs.latest_scores(session, [r.id for r in rows])
    out = []
    for row in rows:
        item = RagConfigVersionOut.model_validate(row)
        item.latest_eval = latest.get(row.id)
        out.append(item)
    return out


@router.get("/active")
async def get_active(_: SuperAdminUser, session: SessionDep) -> ActiveConfigOut:
    version, config = await service.get_active(session)
    latest_eval = None
    if version is not None:
        row = await session.scalar(
            select(RagConfigVersion).where(RagConfigVersion.version == version)
        )
        if row is not None:
            latest_eval = (await eval_runs.latest_scores(session, [row.id])).get(row.id)
    return ActiveConfigOut(version=version, config=config, latest_eval=latest_eval)


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
