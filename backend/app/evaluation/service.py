"""Eval sets and cases (spec §7.1 "test sets"). Functions flush but never commit."""

import csv
import io
import uuid
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.documents.models import Collection, Document
from app.evaluation.models import EvalCase, EvalSet
from app.evaluation.schemas import CaseIn, EvalSetIn, EvalSetUpdate, ImportResult, RowError
from app.users.models import Group, User

MAX_IMPORT_ROWS = 5000
_TRUE = {"true", "1", "yes", "y"}
_FALSE = {"false", "0", "no", "n", ""}


class EvaluationError(Exception):
    code = "evaluation_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(EvaluationError):
    code = "not_found"


class NameTaken(EvaluationError):
    code = "eval_set_name_taken"


class InvalidCase(EvaluationError):
    code = "invalid_case"


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude: uuid.UUID | None = None
) -> None:
    query = select(EvalSet.id).where(func.lower(EvalSet.name) == name.strip().lower())
    if exclude is not None:
        query = query.where(EvalSet.id != exclude)
    if await session.scalar(query) is not None:
        raise NameTaken(f"An eval set named {name.strip()!r} already exists")


async def create_set(session: AsyncSession, actor: User, data: EvalSetIn) -> EvalSet:
    await _ensure_name_free(session, data.name)
    eval_set = EvalSet(
        name=data.name.strip(), description=data.description.strip(), created_by=actor.id
    )
    session.add(eval_set)
    await session.flush()
    await audit.record(
        session,
        action="eval_set.created",
        actor=actor,
        target_type="eval_set",
        target_id=eval_set.id,
        detail={"name": eval_set.name},
    )
    return eval_set


async def get_set(session: AsyncSession, set_id: uuid.UUID) -> EvalSet:
    eval_set = await session.get(EvalSet, set_id)
    if eval_set is None:
        raise NotFound("Eval set not found")
    return eval_set


async def case_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(EvalCase.eval_set_id, func.count()).group_by(EvalCase.eval_set_id)
    )
    return {set_id: count for set_id, count in rows.all()}


async def list_sets(session: AsyncSession) -> list[EvalSet]:
    return list((await session.scalars(select(EvalSet).order_by(EvalSet.name))).all())


async def update_set(
    session: AsyncSession, actor: User, set_id: uuid.UUID, data: EvalSetUpdate
) -> EvalSet:
    eval_set = await get_set(session, set_id)
    if data.name is not None:
        await _ensure_name_free(session, data.name, exclude=eval_set.id)
        eval_set.name = data.name.strip()
    if data.description is not None:
        eval_set.description = data.description.strip()
    await session.flush()
    await audit.record(
        session,
        action="eval_set.updated",
        actor=actor,
        target_type="eval_set",
        target_id=eval_set.id,
        detail=data.model_dump(exclude_none=True),
    )
    return eval_set


async def delete_set(session: AsyncSession, actor: User, set_id: uuid.UUID) -> None:
    eval_set = await get_set(session, set_id)
    await session.delete(eval_set)  # cases and runs go with it (ON DELETE CASCADE)
    await session.flush()
    await audit.record(
        session,
        action="eval_set.deleted",
        actor=actor,
        target_type="eval_set",
        target_id=set_id,
        detail={"name": eval_set.name},
    )


async def _missing(session: AsyncSession, model: Any, ids: Iterable[uuid.UUID]) -> bool:
    wanted = set(ids)
    if not wanted:
        return False
    found = await session.scalar(
        select(func.count()).select_from(model).where(model.id.in_(wanted))
    )
    return int(found or 0) != len(wanted)


async def _validate_docs(session: AsyncSession, data: CaseIn) -> None:
    if await _missing(session, Document, {s.doc_id for s in data.expected_sources}):
        raise InvalidCase("One or more expected source documents do not exist")


async def _validate_refs(session: AsyncSession, data: CaseIn) -> None:
    if await _missing(session, Group, data.run_as_group_ids):
        raise InvalidCase("One or more run-as groups do not exist")
    if await _missing(session, Collection, data.collection_ids):
        raise InvalidCase("One or more collections do not exist")
    await _validate_docs(session, data)


def _apply(case: EvalCase, data: CaseIn) -> None:
    case.question = data.question
    case.expected_answer = data.expected_answer
    case.expected_sources = [
        {"doc_id": str(s.doc_id), "page": s.page} for s in data.expected_sources
    ]
    case.collection_ids = [str(c) for c in dict.fromkeys(data.collection_ids)]
    case.run_as_group_ids = [str(g) for g in dict.fromkeys(data.run_as_group_ids)]
    case.unanswerable = data.unanswerable


async def add_case(
    session: AsyncSession,
    eval_set: EvalSet,
    data: CaseIn,
    *,
    origin: str = "manual",
    source_message_id: uuid.UUID | None = None,
    refs_checked: bool = False,
) -> EvalCase:
    if not refs_checked:
        await _validate_refs(session, data)
    case = EvalCase(eval_set_id=eval_set.id, origin=origin, source_message_id=source_message_id)
    _apply(case, data)
    session.add(case)
    await session.flush()
    return case


async def get_case(session: AsyncSession, case_id: uuid.UUID) -> EvalCase:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise NotFound("Eval case not found")
    return case


async def list_cases(session: AsyncSession, set_id: uuid.UUID) -> list[EvalCase]:
    await get_set(session, set_id)
    query = select(EvalCase).where(EvalCase.eval_set_id == set_id).order_by(EvalCase.seq)
    return list((await session.scalars(query)).all())


async def update_case(session: AsyncSession, case_id: uuid.UUID, data: CaseIn) -> EvalCase:
    case = await get_case(session, case_id)
    await _validate_refs(session, data)
    _apply(case, data)
    await session.flush()
    return case


async def delete_case(session: AsyncSession, case_id: uuid.UUID) -> None:
    await session.delete(await get_case(session, case_id))
    await session.flush()


def _names(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(";") if part.strip()]


def _sources(value: str) -> list[dict[str, object]]:
    """ "<doc_id>[:page];<doc_id>" -> [{"doc_id": ..., "page": ...}]."""
    sources: list[dict[str, object]] = []
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        doc, _, page = part.partition(":")
        sources.append({"doc_id": doc.strip(), "page": int(page) if page.strip() else None})
    return sources


async def import_csv(session: AsyncSession, eval_set: EvalSet, text: str) -> ImportResult:
    """Columns: question (required), expected_answer, expected_sources, collections (names, ';'),
    groups (names, ';'), unanswerable. Good rows are added; bad rows are reported by line."""
    groups = {g.name.lower(): g.id for g in (await session.scalars(select(Group))).all()}
    collections = {c.name.lower(): c.id for c in (await session.scalars(select(Collection))).all()}
    reader = csv.DictReader(io.StringIO(text.removeprefix("﻿")))
    if not reader.fieldnames or "question" not in [f.strip().lower() for f in reader.fieldnames]:
        raise InvalidCase("The CSV needs a header row with at least a 'question' column")
    created, errors = 0, []
    for index, raw in enumerate(reader):
        if index >= MAX_IMPORT_ROWS:
            errors.append(RowError(row=reader.line_num, message="Too many rows; stopped"))
            break
        line = reader.line_num
        if None in raw:  # surplus fields land under the None key
            errors.append(
                RowError(
                    row=line,
                    message="Row has more columns than the header - quote values that "
                    "contain commas",
                )
            )
            continue
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue  # blank line
        try:
            unknown_groups = [n for n in _names(row.get("groups", "")) if n not in groups]
            unknown_colls = [n for n in _names(row.get("collections", "")) if n not in collections]
            if unknown_groups or unknown_colls:
                raise InvalidCase(
                    "Unknown "
                    + ", ".join(
                        [f"group {n!r}" for n in unknown_groups]
                        + [f"collection {n!r}" for n in unknown_colls]
                    )
                )
            flag = row.get("unanswerable", "").lower()
            if flag not in _TRUE | _FALSE:
                raise InvalidCase(f"unanswerable must be true/false, got {flag!r}")
            data = CaseIn.model_validate(
                {
                    "question": row.get("question", ""),
                    "expected_answer": row.get("expected_answer") or None,
                    "expected_sources": _sources(row.get("expected_sources", "")),
                    "collection_ids": [collections[n] for n in _names(row.get("collections", ""))],
                    "run_as_group_ids": [groups[n] for n in _names(row.get("groups", ""))],
                    "unanswerable": flag in _TRUE,
                }
            )
            await _validate_docs(session, data)
            await add_case(session, eval_set, data, origin="csv", refs_checked=True)
            created += 1
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = ".".join(str(part) for part in err["loc"])
            errors.append(RowError(row=line, message=f"{loc}: {err['msg']}"))
        except (InvalidCase, ValueError) as exc:
            message = exc.message if isinstance(exc, InvalidCase) else str(exc).splitlines()[0]
            errors.append(RowError(row=line, message=message))
    return ImportResult(created=created, errors=errors)
