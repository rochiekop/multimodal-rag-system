"""Evaluation admin API: eval sets, cases and CSV import (runs are added in Task 4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.evaluation import service
from app.evaluation.schemas import (
    CaseIn,
    EvalCaseOut,
    EvalSetIn,
    EvalSetOut,
    EvalSetUpdate,
    ImportResult,
)

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
