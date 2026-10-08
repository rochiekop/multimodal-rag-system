"""Evaluation admin API: eval sets, cases and CSV import (runs are added in Task 4)."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.evaluation import runs, service
from app.evaluation.schemas import (
    CaseIn,
    EvalCaseOut,
    EvalResultOut,
    EvalRunDetail,
    EvalRunOut,
    EvalSetIn,
    EvalSetOut,
    EvalSetUpdate,
    ImportResult,
    RunIn,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-evaluation"])
MAX_CSV_BYTES = 2 * 1024 * 1024
_STATUS = {service.NotFound: 404, service.NameTaken: 409, service.InvalidCase: 422}


def _http_error(exc: service.EvaluationError) -> HTTPException:
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


def _set_out(eval_set, counts: dict[uuid.UUID, int]) -> EvalSetOut:  # type: ignore[no-untyped-def]
    out = EvalSetOut.model_validate(eval_set)
    out.case_count = counts.get(eval_set.id, 0)
    return out


@router.get("/eval-sets")
async def list_sets(_: AdminUser, session: SessionDep) -> list[EvalSetOut]:
    counts = await service.case_counts(session)
    return [_set_out(s, counts) for s in await service.list_sets(session)]


@router.post("/eval-sets", status_code=201)
async def create_set(body: EvalSetIn, user: AdminUser, session: SessionDep) -> EvalSetOut:
    try:
        eval_set = await service.create_set(session, user, body)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return _set_out(eval_set, {})


@router.get("/eval-sets/{set_id}")
async def get_set(set_id: uuid.UUID, _: AdminUser, session: SessionDep) -> EvalSetOut:
    try:
        eval_set = await service.get_set(session, set_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    return _set_out(eval_set, await service.case_counts(session))


@router.patch("/eval-sets/{set_id}")
async def update_set(
    set_id: uuid.UUID, body: EvalSetUpdate, user: AdminUser, session: SessionDep
) -> EvalSetOut:
    try:
        eval_set = await service.update_set(session, user, set_id, body)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return _set_out(eval_set, await service.case_counts(session))


@router.delete("/eval-sets/{set_id}", status_code=204)
async def delete_set(set_id: uuid.UUID, user: AdminUser, session: SessionDep) -> Response:
    try:
        await service.delete_set(session, user, set_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return Response(status_code=204)


@router.get("/eval-sets/{set_id}/cases")
async def list_cases(set_id: uuid.UUID, _: AdminUser, session: SessionDep) -> list[EvalCaseOut]:
    try:
        cases = await service.list_cases(session, set_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    return [EvalCaseOut.model_validate(c) for c in cases]


@router.post("/eval-sets/{set_id}/cases", status_code=201)
async def add_case(
    set_id: uuid.UUID, body: CaseIn, _: AdminUser, session: SessionDep
) -> EvalCaseOut:
    try:
        case = await service.add_case(session, await service.get_set(session, set_id), body)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return EvalCaseOut.model_validate(case)


@router.patch("/eval-cases/{case_id}")
async def update_case(
    case_id: uuid.UUID, body: CaseIn, _: AdminUser, session: SessionDep
) -> EvalCaseOut:
    try:
        case = await service.update_case(session, case_id, body)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return EvalCaseOut.model_validate(case)


@router.delete("/eval-cases/{case_id}", status_code=204)
async def delete_case(case_id: uuid.UUID, _: AdminUser, session: SessionDep) -> Response:
    try:
        await service.delete_case(session, case_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return Response(status_code=204)


@router.post("/eval-sets/{set_id}/import")
async def import_cases(
    set_id: uuid.UUID, _: AdminUser, session: SessionDep, file: Annotated[UploadFile, File()]
) -> ImportResult:
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise api_error(413, "file_too_large", "CSV files can be at most 2 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise api_error(422, "invalid_csv", "The CSV must be UTF-8 encoded") from None
    try:
        result = await service.import_csv(session, await service.get_set(session, set_id), text)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return result


@router.post("/eval-runs", status_code=202)
async def start_run(
    body: RunIn, user: AdminUser, session: SessionDep, request: Request
) -> EvalRunOut:
    try:
        run = await runs.create_run(session, user, body.eval_set_id, body.rag_config_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    try:
        request.app.state.enqueue_eval(run.id)
    except Exception:
        logger.exception("Could not queue eval run %s", run.id)
        run.status, run.error = "failed", "Could not queue the run; start it again"
        await session.commit()
        raise api_error(503, "queue_unavailable", "Could not queue the run") from None
    return EvalRunOut.model_validate(run)


@router.get("/eval-runs")
async def list_runs(
    _: AdminUser, session: SessionDep, eval_set_id: uuid.UUID | None = None
) -> list[EvalRunOut]:
    if await runs.reap_stale_runs(session):
        await session.commit()
    return [EvalRunOut.model_validate(r) for r in await runs.list_runs(session, eval_set_id)]


@router.get("/eval-runs/compare")
async def compare_runs(
    a: uuid.UUID, b: uuid.UUID, _: AdminUser, session: SessionDep
) -> dict[str, Any]:
    try:
        return await runs.compare(session, a, b)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None


@router.get("/eval-runs/{run_id}")
async def get_run(run_id: uuid.UUID, _: AdminUser, session: SessionDep) -> EvalRunDetail:
    if await runs.reap_stale_runs(session):
        await session.commit()
    try:
        run, results = await runs.get_run(session, run_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    return EvalRunDetail(
        **EvalRunOut.model_validate(run).model_dump(),
        results=[EvalResultOut.model_validate(r) for r in results],
    )
