"""Review queue API (admin). Viewing content here is audited."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.errors import api_error
from app.auth.deps import AdminUser, SessionDep
from app.evaluation import review
from app.evaluation import service as evaluation
from app.evaluation.schemas import AddToSetIn, EvalCaseOut, MessageReview, ReviewItem

router = APIRouter(prefix="/admin/review-queue", tags=["admin-review"])
_STATUS = {evaluation.NotFound: 404, evaluation.InvalidCase: 422}


def _http_error(exc: evaluation.EvaluationError) -> HTTPException:
    return api_error(_STATUS.get(type(exc), 400), exc.code, exc.message)


@router.get("")
async def list_queue(
    user: AdminUser,
    session: SessionDep,
    kind: review.Kind | None = None,
    include_reviewed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[ReviewItem]:
    items = await review.list_queue(
        session, user, kind=kind, include_reviewed=include_reviewed, limit=limit, offset=offset
    )
    await session.commit()  # keep the audit entry
    return items


@router.get("/messages/{message_id}")
async def message_detail(
    message_id: uuid.UUID, user: AdminUser, session: SessionDep
) -> MessageReview:
    try:
        detail = await review.message_detail(session, user, message_id)
    except evaluation.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return detail


@router.post("/{kind}/{item_id}/reviewed", status_code=204)
async def mark_reviewed(
    kind: review.Kind, item_id: uuid.UUID, user: AdminUser, session: SessionDep
) -> Response:
    try:
        await review.mark_reviewed(session, user, kind, item_id)
    except evaluation.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return Response(status_code=204)


@router.post("/messages/{message_id}/add-to-eval-set", status_code=201)
async def add_to_eval_set(
    message_id: uuid.UUID, body: AddToSetIn, user: AdminUser, session: SessionDep
) -> EvalCaseOut:
    try:
        case = await review.add_message_to_set(session, user, message_id, body)
    except evaluation.EvaluationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return EvalCaseOut.model_validate(case)
