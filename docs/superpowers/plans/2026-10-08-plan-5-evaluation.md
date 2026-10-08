# Plan 5 — Evaluation & Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins build evaluation sets (manually, by CSV import, or from the review queue) and run them against any RagConfig version in the background. The real pipeline runs with the same permissions and guardrails, and each case is scored with Ragas (judge `gpt-5-mini`) plus hit rate, "I don't know" accuracy, latency and cost. Admins can compare two runs question by question with regressions highlighted, and see each config version's latest eval score before activating it. A review queue lists 👎 answers, low-confidence answers and guardrail events, and every admin view of a user's conversation is audited.

**Architecture:** A new `evaluation` module holds:
- eval sets and cases (models, service, CSV import);
- the review queue (queries over `messages` and `guardrail_events`, audited views, add-to-set);
- a case runner that calls a new non-persisting `answer_once()` in `chat/answer.py`;
- a `Scorer` protocol with a Ragas implementation;
- run execution and summaries;
- a Celery task on a new `evaluation` queue, served by a combined worker entry point `app/worker.py`.

Chat provider wiring moves to `chat/wiring.py`, so the api and the worker build identical pipelines. Each eval case runs inside an `eval.case` span tagged with run and case IDs, so it appears in Phoenix.

**Tech Stack:** Plan 1–4 stack + `ragas==0.4.3` (metrics collections: Faithfulness, AnswerRelevancy, ContextPrecisionWithReference / WithoutReference, ContextRecall, AnswerCorrectness; `llm_factory` + `ragas.embeddings.OpenAIEmbeddings` over `openai.AsyncOpenAI`), `langchain-community==0.4.1` (pinned: Ragas 0.4.3 imports `langchain_community.chat_models.vertexai`, which later releases removed), Python `csv`, `statistics`.

**Spec:** `docs/superpowers/specs/2026-10-04-multimodal-rag-v1-design.md` (§7.1, §6.5 Review queue / Evaluation, §6.6 privacy, §4.2 activation warning). Carry-ins: `docs/superpowers/plans/2026-10-07-plan-4-followups.md` ("Carry into Plan 5").

## Decisions this plan relies on (made with the user, 2026-10-08)

- **Ragas, with `langchain-community` pinned to 0.4.1** so Ragas 0.4.3 imports. Revisit when Ragas releases a fix.
- **Judge model `gpt-5-mini`**, stored in `RagConfig.eval_judge_model`.
- **Phoenix: tagged traces, not full experiments.** Every case is traced as `eval.case` with `eval.run_id` and `eval.case_id` attributes, and its trace ID is stored on the result.

## Rulings made while planning

- **"Test sets" are called eval sets in code:** `EvalSet` and `EvalCase`, at `/api/admin/eval-sets`. Classes named `Test*` imported into test modules trigger pytest collection warnings. The UI can still say "test sets". Cost: naming only.
- **Eval runs persist nothing in chat tables.** No conversations, messages, usage records or guardrail events are written, so evaluations never touch users' history, cost caps or strikes. Their cost is reported per run instead. Cost if wrong: eval spend isn't counted toward the installation cap.
- **Every case needs at least one run-as group.** A case with no groups can see nothing and would only measure "not found".
- **"I don't know" detection:** an answer counts as a refusal when the outcome is `not_found`, or when it is `answered` but cites no source. `idk_correct = refusal == case.unanswerable`. Cost if wrong: a correct answer that forgot to cite counts as a refusal.
- **Regression rule in compare:** a question regressed if any shared metric dropped by **≥ 0.1**, if `idk_correct` went from correct to wrong, or if it now errors.
- **Overall score** (shown next to config versions): the mean of the available metric means (hit rate, context precision, context recall, faithfulness, answer relevancy, answer correctness) and the "I don't know" accuracy.
- **Plan 4 carry-in:** pre-flight refusals (rate limit, length, cost caps, chat lock) become guardrail events, at most one per user per check per hour.

## Scope limits (deferred, by design)

- Admin UI for all of this → **Plan 7**.
- Full Phoenix datasets and experiments, synthetic test generation, adversarial sets, nightly scheduled evals, and a blocking activation gate are deferred (spec §1.3 lists most of these as out of scope).
- Plan 4 minor: store `reply_to` on assistant messages → later.
- Eval spend isn't counted toward cost caps (see rulings).

## Global Constraints

- Everything from Plans 1–4 still applies: services never commit; `{"detail": {"code","message"}}` errors; every non-public route authenticated; `/api/admin/*` requires `admin` or higher (route-guard tests in `tests/test_auth.py` stay green); permissions never taken from the client.
- Eval cases have: question, optional expected answer, optional expected sources (`doc_id` + optional page), collection scope, run-as access groups, and an `unanswerable` flag (spec §7.1).
- Runs execute the **real pipeline** (same retrieval permissions and guardrails) as a transient user with the case's run-as groups, using the chosen RagConfig version (or the active one, or defaults when none is active). Runs execute in a **Celery job** (spec §7.1).
- Metrics per case:
  - **Retrieval:** `hit_rate` (only when expected sources are given), `context_precision`, `context_recall` (only with an expected answer).
  - **Answer:** `faithfulness`, `answer_relevancy`, `answer_correctness` (only with an expected answer).
  - **Behaviour:** `idk_correct`.
  - **Operational:** `latency_ms`, `cost_usd`.

  Run summaries add `idk_accuracy`, `latency_p50_ms`, `latency_p95_ms`, `cost_per_question_usd`, `errors` and `score` (spec §7.1).
- Compare shows two runs side by side, per question, with regressions flagged (spec §7.1).
- Every RagConfig version listing shows its latest completed eval score. This is a warning, never a block (spec §7.1).
- The review queue lists 👎 answers, low-confidence answers and guardrail events, and offers "add to eval set". Admins see conversation content only through the review queue, and **every such view is audited** (spec §6.5, §6.6).

## Review Focus

1. **An eval case whose run-as groups can't see the expected document** must get `not_found` and `hit_rate` 0, never content from that document. Test in Task 3 (`test_run_case_respects_run_as_groups`).
2. **A judge or metric failure on one case** must leave that metric `None`; the run still completes and the other cases keep their scores. Tests in Task 3 (`test_scorer_failed_metric_is_none`) and Task 4 (`test_failing_case_is_recorded_and_run_completes`).
3. **A CSV with bad rows** (unknown group or collection, bad page, blank lines, a UTF-8 BOM) must import its good rows and report each bad row with its line number. Test in Task 1 (`test_csv_import_reports_bad_rows`).
4. **An admin opening a user's answer from the review queue** must be audited, with the admin, the message and its owner recorded. Test in Task 2 (`test_viewing_a_message_is_audited`).
5. **Running an evaluation** must never create conversations, messages, usage records or guardrail events. Test in Task 3 (`test_answer_once_saves_nothing`).

---

## File structure (new or changed)

```
backend/
  pyproject.toml                         # + ragas, pinned langchain-community             (T3)
  app/evaluation/__init__.py
  app/evaluation/models.py               # EvalSet, EvalCase, EvalRun, EvalResult           (T1)
  app/evaluation/schemas.py              # CaseIn, outputs                                  (T1, T2, T4)
  app/evaluation/service.py              # sets, cases, CSV import                          (T1)
  app/evaluation/review.py               # review queue, audited view, add-to-set           (T2)
  app/evaluation/scoring.py              # Scorer protocol, RagasScorer, build_ragas_scorer (T3)
  app/evaluation/runner.py               # run_case, deterministic metrics                  (T3)
  app/evaluation/runs.py                 # create/execute runs, summarize, compare          (T4)
  app/evaluation/tasks.py                # Celery task on the evaluation queue              (T4)
  app/worker.py                          # celery entry point for all queues                (T4)
  app/chat/answer.py                     # + contexts on the result, answer_once()          (T3)
  app/chat/wiring.py                     # build_chat_deps (moved from main.py)             (T3)
  app/chat/models.py                     # Message + reviewed_at, reviewed_by               (T1)
  app/guardrails/models.py               # GuardrailEvent + reviewed_at, reviewed_by        (T1)
  app/guardrails/service.py              # + record_preflight_refusal                       (T2)
  app/llm/rag_config.py                  # + eval_judge_model; latest_eval on version out   (T3, T4)
  app/api/admin_evaluation.py            # eval sets, cases, import, runs, compare          (T1, T4)
  app/api/admin_review.py                # review queue                                     (T2)
  app/api/admin_rag_config.py, chat.py, router.py, app/main.py, app/models.py
  migrations/versions/0007_evaluation.py                                                    (T1)
  tests/test_eval_sets.py, test_review_queue.py, test_eval_runner.py, test_eval_runs.py
deploy/docker-compose.yml                # worker: -A app.worker -Q ingestion,evaluation    (T4)
```

---

### Task 1: Eval sets, cases and CSV import

**Files:**
- Create: `backend/app/evaluation/__init__.py` (empty), `backend/app/evaluation/models.py`, `backend/app/evaluation/schemas.py`, `backend/app/evaluation/service.py`, `backend/app/api/admin_evaluation.py`, `backend/migrations/versions/0007_evaluation.py`, `backend/tests/test_eval_sets.py`
- Modify: `backend/app/chat/models.py`, `backend/app/guardrails/models.py`, `backend/app/api/router.py`, `backend/app/models.py`

**Interfaces:**
- Produces:
  - Models `EvalSet(id, name, description, created_by, created_at)`; `EvalCase(id, seq, eval_set_id, question, expected_answer, expected_sources: list[{"doc_id": str, "page": int|None}], collection_ids: list[str], run_as_group_ids: list[str], unanswerable, origin, source_message_id, created_at)`; `EvalRun` and `EvalResult` (tables created here, used in Task 4).
  - `Message.reviewed_at/reviewed_by` and `GuardrailEvent.reviewed_at/reviewed_by` (used in Task 2).
  - Schemas `CaseIn`, `ExpectedSource`, `EvalSetIn`, `EvalSetUpdate`, `EvalSetOut`, `EvalCaseOut`, `ImportResult`, `RowError`.
  - Service:
    - `create_set(session, actor, data) -> EvalSet`, `list_sets(session)`, `get_set(session, set_id)`, `update_set(session, actor, set_id, data)`, `delete_set(session, actor, set_id)`;
    - `add_case(session, eval_set, data, *, origin="manual", source_message_id=None) -> EvalCase`, `list_cases(session, set_id)`, `update_case(session, case_id, data)`, `delete_case(session, case_id)`;
    - `import_csv(session, eval_set, text) -> ImportResult`.
  - Errors `EvaluationError` (class `code`), `NotFound` (404), `NameTaken` (409), `InvalidCase` (422).
  - Routes:
    - `GET|POST /api/admin/eval-sets`
    - `GET|PATCH|DELETE /api/admin/eval-sets/{set_id}`
    - `GET|POST /api/admin/eval-sets/{set_id}/cases`
    - `PATCH|DELETE /api/admin/eval-cases/{case_id}`
    - `POST /api/admin/eval-sets/{set_id}/import` (multipart field `file`)

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_eval_sets.py`

```python
import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.models import EvalCase
from app.users.models import Role
from tests.factories import bearer, login, make_collection, make_group, make_user


async def _admin(client: AsyncClient, session: AsyncSession) -> dict[str, str]:
    await make_user(session, username="boss", role=Role.ADMIN)
    return bearer(await login(client, "boss"))


async def _set(client: AsyncClient, h: dict[str, str], name: str = "HR basics") -> str:
    response = await client.post("/api/admin/eval-sets", headers=h, json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_sets_are_created_renamed_listed_and_unique(
    client: AsyncClient, session: AsyncSession
) -> None:
    h = await _admin(client, session)
    set_id = await _set(client, h)
    duplicate = await client.post("/api/admin/eval-sets", headers=h, json={"name": "HR basics"})
    assert duplicate.status_code == 409
    renamed = await client.patch(
        f"/api/admin/eval-sets/{set_id}", headers=h, json={"description": "Leave and pay"}
    )
    assert renamed.json()["description"] == "Leave and pay"
    listed = (await client.get("/api/admin/eval-sets", headers=h)).json()
    assert [(s["name"], s["case_count"]) for s in listed] == [("HR basics", 0)]


async def test_cases_are_validated(client: AsyncClient, session: AsyncSession) -> None:
    h = await _admin(client, session)
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    set_id = await _set(client, h)
    url = f"/api/admin/eval-sets/{set_id}/cases"

    ok = await client.post(
        url,
        headers=h,
        json={
            "question": "  How many leave days?  ",
            "expected_answer": "25 days",
            "collection_ids": [str(coll.id)],
            "run_as_group_ids": [str(hr.id)],
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["question"] == "How many leave days?"
    assert ok.json()["origin"] == "manual"

    no_groups = await client.post(url, headers=h, json={"question": "q", "run_as_group_ids": []})
    assert no_groups.status_code == 422
    unknown_group = await client.post(
        url, headers=h, json={"question": "q", "run_as_group_ids": [str(uuid.uuid4())]}
    )
    assert unknown_group.status_code == 422
    assert unknown_group.json()["detail"]["code"] == "invalid_case"
    unknown_doc = await client.post(
        url,
        headers=h,
        json={
            "question": "q",
            "run_as_group_ids": [str(hr.id)],
            "expected_sources": [{"doc_id": str(uuid.uuid4()), "page": 2}],
        },
    )
    assert unknown_doc.status_code == 422


async def test_cases_update_delete_and_set_delete_cascades(
    client: AsyncClient, session: AsyncSession
) -> None:
    h = await _admin(client, session)
    hr = await make_group(session, "hr")
    set_id = await _set(client, h)
    case = (
        await client.post(
            f"/api/admin/eval-sets/{set_id}/cases",
            headers=h,
            json={"question": "q1", "run_as_group_ids": [str(hr.id)]},
        )
    ).json()
    updated = await client.patch(
        f"/api/admin/eval-cases/{case['id']}",
        headers=h,
        json={"question": "q2", "run_as_group_ids": [str(hr.id)], "unanswerable": True},
    )
    assert (updated.json()["question"], updated.json()["unanswerable"]) == ("q2", True)

    assert (await client.delete(f"/api/admin/eval-sets/{set_id}", headers=h)).status_code == 204
    assert await session.scalar(select(func.count()).select_from(EvalCase)) == 0
    assert (await client.get(f"/api/admin/eval-sets/{set_id}", headers=h)).status_code == 404


async def test_csv_import_reports_bad_rows(client: AsyncClient, session: AsyncSession) -> None:
    h = await _admin(client, session)
    await make_group(session, "hr")
    await make_group(session, "mgmt")
    await make_collection(session, "HR")
    set_id = await _set(client, h)
    doc_id = uuid.uuid4()
    csv_text = (
        "﻿question,expected_answer,expected_sources,collections,groups,unanswerable\n"
        "How many leave days?,25 days,,HR,hr;MGMT,false\n"
        "\n"
        "Who is the CEO?,,,,hr,yes\n"
        "Bad group,,,,nobody,no\n"
        f"Bad source,,{doc_id}:x,,hr,no\n"
        "Bad collection,,,Finance,hr,no\n"
        ",,,,hr,no\n"
    )
    response = await client.post(
        f"/api/admin/eval-sets/{set_id}/import",
        headers=h,
        files={"file": ("cases.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 2
    assert [e["row"] for e in body["errors"]] == [5, 6, 7, 8]
    cases = (await client.get(f"/api/admin/eval-sets/{set_id}/cases", headers=h)).json()
    assert [c["question"] for c in cases] == ["How many leave days?", "Who is the CEO?"]
    assert len(cases[0]["run_as_group_ids"]) == 2 and cases[1]["unanswerable"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_eval_sets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation'`

- [ ] **Step 3: Implement**

`backend/app/evaluation/models.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EvalSet(Base):
    """A named evaluation set ("test set" in the spec)."""

    __tablename__ = "eval_sets"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalCase(Base):
    __tablename__ = "eval_cases"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))  # stable order
    eval_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    collection_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    run_as_group_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    unanswerable: Mapped[bool] = mapped_column(default=False)
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # manual | csv | review
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    eval_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    rag_config_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rag_config_versions.id", ondelete="SET NULL"), index=True
    )
    rag_config_version: Mapped[int | None]
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)  # snapshot actually used
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed
    error: Mapped[str | None] = mapped_column(String(1000))
    case_count: Mapped[int] = mapped_column(default=0)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalResult(Base):
    __tablename__ = "eval_results"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="SET NULL")
    )
    case_seq: Mapped[int] = mapped_column(BigInteger, default=0)  # display order
    question: Mapped[str] = mapped_column(Text)
    unanswerable: Mapped[bool] = mapped_column(default=False)
    outcome: Mapped[str] = mapped_column(String(20))
    answer: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/chat/models.py` — add to `Message` after `feedback_at`:

```python
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None]
```

`backend/app/guardrails/models.py` — add the same two columns to `GuardrailEvent` after `detail`.

`backend/app/models.py` — import and export `EvalSet`, `EvalCase`, `EvalRun`, `EvalResult`.

`backend/app/evaluation/schemas.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExpectedSource(BaseModel):
    doc_id: uuid.UUID
    page: int | None = Field(default=None, ge=1)


class CaseIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str | None = Field(default=None, max_length=8000)
    expected_sources: list[ExpectedSource] = Field(default_factory=list, max_length=20)
    collection_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    run_as_group_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    unanswerable: bool = False

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value

    @field_validator("expected_answer")
    @classmethod
    def _blank_answer_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class EvalSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class EvalSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class EvalSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    case_count: int = 0
    created_at: datetime


class EvalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    eval_set_id: uuid.UUID
    question: str
    expected_answer: str | None
    expected_sources: list[dict[str, Any]]
    collection_ids: list[str]
    run_as_group_ids: list[str]
    unanswerable: bool
    origin: str
    source_message_id: uuid.UUID | None
    created_at: datetime


class RowError(BaseModel):
    row: int  # 1-based line number in the file, header = line 1
    message: str


class ImportResult(BaseModel):
    created: int
    errors: list[RowError]
```

`backend/app/evaluation/service.py`:

```python
"""Eval sets and cases (spec §7.1 "test sets"). Functions flush but never commit."""

import csv
import io
import uuid
from collections.abc import Iterable

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
        session, action="eval_set.created", actor=actor, target_type="eval_set",
        target_id=eval_set.id, detail={"name": eval_set.name},
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
        session, action="eval_set.updated", actor=actor, target_type="eval_set",
        target_id=eval_set.id, detail=data.model_dump(exclude_none=True),
    )
    return eval_set


async def delete_set(session: AsyncSession, actor: User, set_id: uuid.UUID) -> None:
    eval_set = await get_set(session, set_id)
    await session.delete(eval_set)  # cases and runs go with it (ON DELETE CASCADE)
    await session.flush()
    await audit.record(
        session, action="eval_set.deleted", actor=actor, target_type="eval_set",
        target_id=set_id, detail={"name": eval_set.name},
    )


async def _validate_refs(session: AsyncSession, data: CaseIn) -> None:
    async def missing(model: type, ids: Iterable[uuid.UUID]) -> bool:
        wanted = set(ids)
        if not wanted:
            return False
        found = await session.scalar(
            select(func.count()).select_from(model).where(model.id.in_(wanted))  # type: ignore[attr-defined]
        )
        return int(found or 0) != len(wanted)

    if await missing(Group, data.run_as_group_ids):
        raise InvalidCase("One or more run-as groups do not exist")
    if await missing(Collection, data.collection_ids):
        raise InvalidCase("One or more collections do not exist")
    if await missing(Document, {s.doc_id for s in data.expected_sources}):
        raise InvalidCase("One or more expected source documents do not exist")


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
) -> EvalCase:
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
    """"<doc_id>[:page];<doc_id>" -> [{"doc_id": ..., "page": ...}]."""
    sources = []
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
    collections = {
        c.name.lower(): c.id for c in (await session.scalars(select(Collection))).all()
    }
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or "question" not in [f.strip() for f in reader.fieldnames]:
        raise InvalidCase("The CSV needs a header row with at least a 'question' column")
    created, errors = 0, []
    for index, raw in enumerate(reader):
        if index >= MAX_IMPORT_ROWS:
            errors.append(RowError(row=reader.line_num, message="Too many rows; stopped"))
            break
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue  # blank line
        line = reader.line_num
        try:
            unknown_groups = [n for n in _names(row.get("groups", "")) if n not in groups]
            unknown_colls = [n for n in _names(row.get("collections", "")) if n not in collections]
            if unknown_groups or unknown_colls:
                raise InvalidCase(
                    "Unknown " + ", ".join(
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
            await add_case(session, eval_set, data, origin="csv")
            created += 1
        except (InvalidCase, ValidationError, ValueError) as exc:
            message = exc.message if isinstance(exc, InvalidCase) else str(exc).splitlines()[0]
            errors.append(RowError(row=line, message=message))
    return ImportResult(created=created, errors=errors)
```

Note: `reader.line_num` is the physical line just read, so with the header on line 1 the test's rows are lines 2–8 (blank line 3 skipped). The bad rows are 5 (unknown group), 6 (page `x`), 7 (unknown collection) and 8 (empty question).

`backend/app/api/admin_evaluation.py`:

```python
"""Evaluation admin API: eval sets, cases and CSV import (runs are added in Task 4)."""

import uuid

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
    set_id: uuid.UUID, _: AdminUser, session: SessionDep, file: UploadFile = File(...)
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
```

`backend/app/api/router.py` — include `admin_evaluation.router`.

`backend/migrations/versions/0007_evaluation.py` (revision `"0007"`, down_revision `"0006"`, Create Date 2026-10-08). `upgrade()` creates:
- `eval_sets`, `eval_cases`, `eval_runs` and `eval_results`, matching the models above column for column. Use `op.f(...)` names: `pk_<table>`, `uq_eval_sets_name`, `fk_<table>_<column>_<referred_table>`, `ix_<table>_<column>` for every `index=True` column. Every JSONB column (`postgresql.JSONB(astext_type=sa.Text())`) is `nullable=False`, and nullability otherwise follows the model's `Mapped[... | None]`. `seq` and `case_seq` use `sa.BigInteger()`, and `eval_cases.seq` has `sa.Identity(always=True)`.
- `messages.reviewed_at` (timestamptz, null) and `messages.reviewed_by` (uuid, null); `guardrail_events.reviewed_at` and `guardrail_events.reviewed_by`.

`downgrade()` reverses them in order. Follow the style of `0006_guardrails.py`, including the `_now()` helper for `created_at`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_eval_sets.py tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(evaluation): eval sets and cases with validation and csv import"
```

---

### Task 2: Review queue (audited), add-to-set, pre-flight refusal events

**Files:**
- Create: `backend/app/evaluation/review.py`, `backend/app/api/admin_review.py`, `backend/tests/test_review_queue.py`
- Modify: `backend/app/evaluation/schemas.py`, `backend/app/guardrails/service.py`, `backend/app/api/chat.py`, `backend/app/api/router.py`

**Interfaces:**
- Consumes: Task 1 (`add_case`, `get_set`, `CaseIn`, `InvalidCase`, `NotFound`, the review columns); Plan 4 (`GuardrailEvent`, `record_event`, `GuardrailRefusal`).
- Produces:
  - `review.list_queue(session, *, kind, include_reviewed, limit, offset) -> list[ReviewItem]`, where `kind` is `"feedback" | "low_confidence" | "guardrail" | None`;
  - `review.mark_reviewed(session, actor, kind, item_id)`;
  - `review.message_detail(session, actor, message_id) -> MessageReview` (audited `review.message_viewed`);
  - `review.add_message_to_set(session, actor, message_id, data: AddToSetIn) -> EvalCase`;
  - `guardrails.service.record_preflight_refusal(session, *, user, code, settings)`.
  - Routes (admin):
    - `GET /api/admin/review-queue?kind=&include_reviewed=&limit=&offset=` (audited `review.queue_viewed`)
    - `GET /api/admin/review-queue/messages/{message_id}`
    - `POST /api/admin/review-queue/{kind}/{item_id}/reviewed`
    - `POST /api/admin/review-queue/messages/{message_id}/add-to-eval-set`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_review_queue.py`

```python
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.chat.models import Conversation, Message
from app.evaluation.models import EvalSet
from app.guardrails.models import GuardrailEvent
from app.users.models import Role, User
from tests.factories import (
    activate_config,
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
)


async def _exchange(
    session: AsyncSession,
    user: User,
    question: str,
    answer: str,
    *,
    rating: int | None = None,
    low_confidence: bool = False,
    collection_ids: list[str] | None = None,
) -> Message:
    conversation = Conversation(user_id=user.id, title=question[:50])
    session.add(conversation)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=question,
            collection_ids=collection_ids or [],
        )
    )
    await session.flush()
    reply = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        outcome="answered",
        collection_ids=collection_ids or [],
        feedback_rating=rating,
        feedback_at=datetime.now(UTC) if rating else None,
        low_confidence=low_confidence,
    )
    session.add(reply)
    await session.commit()
    return reply


async def _world(client: AsyncClient, session: AsyncSession):
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    alice = await make_user(session, username="alice", groups=[hr])
    await make_user(session, username="boss", role=Role.ADMIN)
    disliked = await _exchange(
        session, alice, "How many leave days?", "30 days.", rating=-1,
        collection_ids=[str(coll.id)],
    )
    shaky = await _exchange(session, alice, "Parking?", "Free.", low_confidence=True)
    await _exchange(session, alice, "Fine one", "All good.", rating=1)
    session.add(
        GuardrailEvent(user_id=alice.id, check="prompt_injection", action="blocked", strike=True)
    )
    await session.commit()
    return alice, coll, disliked, shaky, bearer(await login(client, "boss"))


async def test_queue_lists_feedback_low_confidence_and_guardrail_items(
    client: AsyncClient, session: AsyncSession
) -> None:
    _, _, disliked, shaky, h = await _world(client, session)
    items = (await client.get("/api/admin/review-queue", headers=h)).json()
    assert sorted(i["kind"] for i in items) == ["feedback", "guardrail", "low_confidence"]
    feedback = next(i for i in items if i["kind"] == "feedback")
    assert feedback["message_id"] == str(disliked.id)
    assert (feedback["question"], feedback["answer"], feedback["username"]) == (
        "How many leave days?", "30 days.", "alice",
    )
    only = await client.get("/api/admin/review-queue", headers=h, params={"kind": "low_confidence"})
    assert [i["message_id"] for i in only.json()] == [str(shaky.id)]

    marked = await client.post(
        f"/api/admin/review-queue/feedback/{disliked.id}/reviewed", headers=h
    )
    assert marked.status_code == 204
    remaining = (await client.get("/api/admin/review-queue", headers=h)).json()
    assert "feedback" not in [i["kind"] for i in remaining]
    everything = await client.get(
        "/api/admin/review-queue", headers=h, params={"include_reviewed": "true"}
    )
    assert "feedback" in [i["kind"] for i in everything.json()]
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "review.queue_viewed" in actions


async def test_viewing_a_message_is_audited(client: AsyncClient, session: AsyncSession) -> None:
    alice, _, disliked, _, h = await _world(client, session)
    detail = await client.get(f"/api/admin/review-queue/messages/{disliked.id}", headers=h)
    assert detail.status_code == 200
    body = detail.json()
    assert (body["question"], body["answer"]["content"], body["user"]["username"]) == (
        "How many leave days?", "30 days.", "alice",
    )
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == "review.message_viewed")
    )
    assert entry is not None
    assert entry.actor_username == "boss"
    assert entry.target_id == str(disliked.id)
    assert entry.detail["owner_id"] == str(alice.id)


async def test_add_message_to_eval_set(client: AsyncClient, session: AsyncSession) -> None:
    alice, coll, disliked, _, h = await _world(client, session)
    eval_set = EvalSet(name="From review")
    session.add(eval_set)
    await session.commit()
    response = await client.post(
        f"/api/admin/review-queue/messages/{disliked.id}/add-to-eval-set",
        headers=h,
        json={"eval_set_id": str(eval_set.id), "expected_answer": "25 days"},
    )
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["question"] == "How many leave days?"
    assert case["expected_answer"] == "25 days"
    assert case["collection_ids"] == [str(coll.id)]
    assert case["run_as_group_ids"] == [str(g.id) for g in alice.groups]
    assert (case["origin"], case["source_message_id"]) == ("review", str(disliked.id))

    loner = await make_user(session, username="loner")
    lonely = await _exchange(session, loner, "Q?", "A.", rating=-1)
    no_groups = await client.post(
        f"/api/admin/review-queue/messages/{lonely.id}/add-to-eval-set",
        headers=h,
        json={"eval_set_id": str(eval_set.id)},
    )
    assert no_groups.status_code == 422


async def test_preflight_refusals_are_recorded_once_per_hour(
    app: FastAPI, client: AsyncClient, session: AsyncSession
) -> None:
    hr = await make_group(session, "hr")
    await make_user(session, username="alice", groups=[hr])
    app.state.chat_deps = chat_deps(app.state.index)
    await activate_config(session, guardrails={"max_question_chars": 10})
    token = await login(client, "alice")
    for _ in range(2):
        response = await client.post(
            "/api/chat", headers=bearer(token), json={"question": "x" * 11}
        )
        assert response.status_code == 422
    count = await session.scalar(
        select(func.count()).select_from(GuardrailEvent).where(
            GuardrailEvent.check == "question_too_long"
        )
    )
    assert count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_review_queue.py -v`
Expected: FAIL (404 for `/api/admin/review-queue`, and `ImportError` once the module is referenced)

- [ ] **Step 3: Implement**

`backend/app/evaluation/schemas.py` — append:

```python
class ReviewItem(BaseModel):
    kind: str  # feedback | low_confidence | guardrail
    id: uuid.UUID  # message id (feedback, low_confidence) or guardrail event id
    created_at: datetime
    user_id: uuid.UUID
    username: str
    message_id: uuid.UUID | None
    question: str | None
    answer: str | None
    detail: dict[str, Any]
    reviewed_at: datetime | None


class ReviewUser(BaseModel):
    id: uuid.UUID
    username: str


class ReviewAnswer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    outcome: str | None
    sources: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    low_confidence: bool
    guardrail: dict[str, Any] | None
    feedback_rating: int | None
    feedback_comment: str | None
    created_at: datetime


class MessageReview(BaseModel):
    conversation_id: uuid.UUID
    user: ReviewUser
    question: str | None
    answer: ReviewAnswer


class AddToSetIn(BaseModel):
    eval_set_id: uuid.UUID
    expected_answer: str | None = Field(default=None, max_length=8000)
    unanswerable: bool = False
```

`backend/app/evaluation/review.py`:

```python
"""Review queue (spec §6.5): 👎 answers, low-confidence answers and guardrail events.
Admins see conversation content only here, and every view is audited (spec §6.6).
Functions flush but never commit."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.chat.models import Conversation, Message
from app.evaluation import service as evaluation
from app.evaluation.models import EvalCase
from app.evaluation.schemas import (
    AddToSetIn,
    CaseIn,
    MessageReview,
    ReviewAnswer,
    ReviewItem,
    ReviewUser,
)
from app.guardrails.models import GuardrailEvent
from app.users.models import User

Kind = Literal["feedback", "low_confidence", "guardrail"]
KINDS: tuple[Kind, ...] = ("feedback", "low_confidence", "guardrail")
SNIPPET = 300


async def _question_for(session: AsyncSession, message: Message) -> str | None:
    """The user question this assistant message answered (the user message just before it)."""
    query = (
        select(Message.content)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.role == "user",
            Message.seq < message.seq,
        )
        .order_by(Message.seq.desc())
        .limit(1)
    )
    return await session.scalar(query)


async def _message_items(
    session: AsyncSession, kind: Kind, include_reviewed: bool, limit: int
) -> list[ReviewItem]:
    query = (
        select(Message, User)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(User, User.id == Conversation.user_id)
        .where(Message.role == "assistant")
    )
    if kind == "feedback":
        query = query.where(Message.feedback_rating == -1).order_by(Message.feedback_at.desc())
    else:
        query = query.where(Message.low_confidence.is_(True)).order_by(Message.created_at.desc())
    if not include_reviewed:
        query = query.where(Message.reviewed_at.is_(None))
    items = []
    for message, owner in (await session.execute(query.limit(limit))).all():
        question = await _question_for(session, message)
        items.append(
            ReviewItem(
                kind=kind,
                id=message.id,
                created_at=(message.feedback_at if kind == "feedback" else None)
                or message.created_at,
                user_id=owner.id,
                username=owner.username,
                message_id=message.id,
                question=question[:SNIPPET] if question else None,
                answer=message.content[:SNIPPET],
                detail={"comment": message.feedback_comment} if kind == "feedback" else {},
                reviewed_at=message.reviewed_at,
            )
        )
    return items


async def _guardrail_items(
    session: AsyncSession, include_reviewed: bool, limit: int
) -> list[ReviewItem]:
    query = (
        select(GuardrailEvent, User)
        .join(User, User.id == GuardrailEvent.user_id)
        .order_by(GuardrailEvent.created_at.desc())
    )
    if not include_reviewed:
        query = query.where(GuardrailEvent.reviewed_at.is_(None))
    items = []
    for event, owner in (await session.execute(query.limit(limit))).all():
        message = await session.get(Message, event.message_id) if event.message_id else None
        question = await _question_for(session, message) if message else None
        items.append(
            ReviewItem(
                kind="guardrail",
                id=event.id,
                created_at=event.created_at,
                user_id=owner.id,
                username=owner.username,
                message_id=event.message_id,
                question=question[:SNIPPET] if question else None,
                answer=message.content[:SNIPPET] if message else None,
                detail={
                    "check": event.check,
                    "category": event.category,
                    "action": event.action,
                    "strike": event.strike,
                },
                reviewed_at=event.reviewed_at,
            )
        )
    return items


async def list_queue(
    session: AsyncSession,
    actor: User,
    *,
    kind: Kind | None = None,
    include_reviewed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[ReviewItem]:
    wanted = [kind] if kind else list(KINDS)
    items: list[ReviewItem] = []
    for k in wanted:
        if k == "guardrail":
            items += await _guardrail_items(session, include_reviewed, limit + offset)
        else:
            items += await _message_items(session, k, include_reviewed, limit + offset)
    items.sort(key=lambda i: i.created_at, reverse=True)
    await audit.record(
        session,
        action="review.queue_viewed",
        actor=actor,
        target_type="review_queue",
        detail={"kind": kind, "include_reviewed": include_reviewed, "offset": offset},
    )
    return items[offset : offset + limit]


async def _assistant_message(session: AsyncSession, message_id: uuid.UUID) -> Message:
    message = await session.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise evaluation.NotFound("Message not found")
    return message


async def mark_reviewed(
    session: AsyncSession, actor: User, kind: Kind, item_id: uuid.UUID
) -> None:
    target: Message | GuardrailEvent | None
    if kind == "guardrail":
        target = await session.get(GuardrailEvent, item_id)
    else:
        target = await session.get(Message, item_id)
    if target is None:
        raise evaluation.NotFound("Review item not found")
    target.reviewed_at = datetime.now(UTC)
    target.reviewed_by = actor.id
    await session.flush()
    await audit.record(
        session, action="review.marked_reviewed", actor=actor, target_type=kind,
        target_id=item_id,
    )


async def message_detail(
    session: AsyncSession, actor: User, message_id: uuid.UUID
) -> MessageReview:
    message = await _assistant_message(session, message_id)
    conversation = await session.get(Conversation, message.conversation_id)
    assert conversation is not None
    owner = await session.get(User, conversation.user_id)
    assert owner is not None
    await audit.record(
        session,
        action="review.message_viewed",
        actor=actor,
        target_type="message",
        target_id=message.id,
        detail={"owner_id": str(owner.id), "conversation_id": str(conversation.id)},
    )
    return MessageReview(
        conversation_id=conversation.id,
        user=ReviewUser(id=owner.id, username=owner.username),
        question=await _question_for(session, message),
        answer=ReviewAnswer.model_validate(message),
    )


async def add_message_to_set(
    session: AsyncSession, actor: User, message_id: uuid.UUID, data: AddToSetIn
) -> EvalCase:
    message = await _assistant_message(session, message_id)
    question = await _question_for(session, message)
    conversation = await session.get(Conversation, message.conversation_id)
    owner = await session.get(User, conversation.user_id) if conversation else None
    if question is None or owner is None:
        raise evaluation.InvalidCase("This answer has no question to evaluate")
    if not owner.groups:
        raise evaluation.InvalidCase("The user who asked this has no groups to run as")
    eval_set = await evaluation.get_set(session, data.eval_set_id)
    case = await evaluation.add_case(
        session,
        eval_set,
        CaseIn(
            question=question,
            expected_answer=data.expected_answer,
            collection_ids=[uuid.UUID(c) for c in message.collection_ids],
            run_as_group_ids=[g.id for g in owner.groups],
            unanswerable=data.unanswerable,
        ),
        origin="review",
        source_message_id=message.id,
    )
    await audit.record(
        session, action="review.added_to_eval_set", actor=actor, target_type="message",
        target_id=message.id, detail={"eval_set_id": str(eval_set.id), "case_id": str(case.id)},
    )
    return case
```

`backend/app/api/admin_review.py`:

```python
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
```

Register it in `router.py`.

`backend/app/guardrails/service.py` — append:

```python
async def record_preflight_refusal(
    session: AsyncSession, *, user: User, code: str, settings: GuardrailSettings
) -> None:
    """Record a pre-flight refusal (rate limit, length, cost cap, lock) at most once per user,
    check and hour, so admins see it without the log being flooded."""
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = await session.scalar(
        select(GuardrailEvent.id)
        .where(
            GuardrailEvent.user_id == user.id,
            GuardrailEvent.check == code,
            GuardrailEvent.created_at >= since,
        )
        .limit(1)
    )
    if recent is None:
        await record_event(session, user=user, check=code, action="blocked", settings=settings)
```

`backend/app/api/chat.py` — in the `except GuardrailRefusal as exc:` block, before `await session.commit()`, add (import `from app.guardrails import service as guardrails`):

```python
        await guardrails.record_preflight_refusal(
            session, user=user, code=exc.code, settings=config.guardrails
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_review_queue.py tests/test_chat_limits.py tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(evaluation): audited review queue, add-to-eval-set and pre-flight refusal events"
```

---

### Task 3: Non-persisting pipeline run, case runner and Ragas scoring

**Files:**
- Create: `backend/app/chat/wiring.py`, `backend/app/evaluation/scoring.py`, `backend/app/evaluation/runner.py`, `backend/tests/test_eval_runner.py`
- Modify: `backend/pyproject.toml`, `backend/app/chat/answer.py`, `backend/app/main.py`, `backend/app/llm/rag_config.py`

**Interfaces:**
- Consumes: Plan 3/4 `answer.py` internals (`_run`, `_Result`, `_Usage`); `visible_collections`; `compute_cost`; `answer_span`; Task 1 `EvalCase`.
- Produces:
  - `answer.PipelineResult` (alias of `_Result`, plus a new `contexts: list[str]` holding the full texts of retrieved chunks) and `answer.Usage` (alias of `_Usage`);
  - `answer.answer_once(sessionmaker, deps, config, *, user, question, collection_ids=()) -> tuple[PipelineResult, Usage]`;
  - `app.chat.wiring.build_chat_deps(settings, index) -> ChatDeps`;
  - `RagConfig.eval_judge_model: str = "gpt-5-mini"`;
  - `scoring`: `METRICS`, `ScoreInput(question, answer, contexts, reference, answered)`, the `Scorer` protocol (`async score(item) -> dict[str, float | None]`), `RagasScorer(...)`, `build_ragas_scorer(settings, judge_model) -> RagasScorer`;
  - `runner`: `CaseOutcome`, `is_refusal(outcome, citations) -> bool`, `deterministic_metrics(case, outcome) -> dict[str, float | None]`, `run_case(sessionmaker, deps, config, case, groups, *, run_id) -> CaseOutcome`.

- [ ] **Step 1: Add dependencies**

```bash
cd backend && uv add "ragas==0.4.3" "langchain-community==0.4.1"
uv run python -W ignore -c "from ragas.metrics.collections import Faithfulness, AnswerRelevancy, ContextPrecisionWithReference, ContextPrecisionWithoutReference, ContextRecall, AnswerCorrectness; from ragas.llms import llm_factory; from ragas.embeddings import OpenAIEmbeddings; print('ok')"
```
Expected: `ok`. Ragas 0.4.3 needs `langchain_community.chat_models.vertexai`, which `langchain-community` 0.4.2 removed; keep the pin.

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_eval_runner.py`

```python
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.chat.answer import answer_once
from app.chat.models import Message
from app.core.config import Settings
from app.core.db import create_sessionmaker
from app.evaluation.models import EvalCase
from app.evaluation.runner import deterministic_metrics, is_refusal, run_case
from app.evaluation.scoring import RagasScorer, ScoreInput, build_ragas_scorer
from app.guardrails.models import GuardrailEvent, UsageRecord
from app.ingestion.index import ChunkIndex
from app.llm.rag_config import RagConfig
from app.users.models import User
from tests.factories import chat_deps, make_collection, make_group, seed_document


async def _world(session: AsyncSession, index: ChunkIndex):
    hr = await make_group(session, "hr")
    eng = await make_group(session, "eng")
    coll = await make_collection(session, "HR", [hr])
    doc = await seed_document(session, index, coll, ["Annual leave is 25 days per year."])
    return hr, eng, coll, doc


async def test_answer_once_saves_nothing(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr, _, _, _ = await _world(session, chunk_index)
    user = User(id=uuid.uuid4(), username="eval", groups=[hr])
    result, usage = await answer_once(
        create_sessionmaker(engine), chat_deps(chunk_index), RagConfig(),
        user=user, question="How many leave days?",
    )
    assert result.outcome == "answered"
    assert result.contexts == ["Annual leave is 25 days per year."]
    assert result.citations and isinstance(usage.tokens, dict)
    for model in (Message, UsageRecord, GuardrailEvent):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_run_case_respects_run_as_groups(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    hr, eng, _, doc = await _world(session, chunk_index)
    case = EvalCase(
        question="How many leave days?",
        expected_sources=[{"doc_id": str(doc.id), "page": 1}],
        run_as_group_ids=[str(eng.id)],
    )
    outsider = await run_case(
        create_sessionmaker(engine), chat_deps(chunk_index), RagConfig(), case, [eng],
        run_id=uuid.uuid4(),
    )
    assert outsider.outcome == "not_found" and outsider.contexts == []
    assert deterministic_metrics(case, outsider)["hit_rate"] == 0.0

    insider = await run_case(
        create_sessionmaker(engine), chat_deps(chunk_index), RagConfig(), case, [hr],
        run_id=uuid.uuid4(),
    )
    assert insider.outcome == "answered" and insider.error is None
    assert insider.latency_ms >= 0 and insider.answer
    assert deterministic_metrics(case, insider)["hit_rate"] == 1.0


def test_refusal_and_idk_metrics() -> None:
    answered = SimpleNamespace(outcome="answered", citations=[{"n": 1}], sources=[])
    uncited = SimpleNamespace(outcome="answered", citations=[], sources=[])
    not_found = SimpleNamespace(outcome="not_found", citations=[], sources=[])
    assert not is_refusal("answered", [{"n": 1}])
    assert is_refusal("answered", []) and is_refusal("not_found", [])

    answerable = EvalCase(question="q", unanswerable=False, expected_sources=[])
    unanswerable = EvalCase(question="q", unanswerable=True, expected_sources=[])
    assert deterministic_metrics(answerable, answered) == {"hit_rate": None, "idk_correct": 1.0}
    assert deterministic_metrics(answerable, uncited)["idk_correct"] == 0.0
    assert deterministic_metrics(unanswerable, not_found)["idk_correct"] == 1.0
    assert deterministic_metrics(unanswerable, answered)["idk_correct"] == 0.0


class _Metric:
    def __init__(self, value: float | Exception) -> None:
        self.value = value
        self.calls: list[dict[str, Any]] = []

    async def ascore(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self.value, Exception):
            raise self.value
        return SimpleNamespace(value=self.value)


def _scorer(**overrides: float | Exception) -> tuple[RagasScorer, dict[str, _Metric]]:
    names = (
        "faithfulness", "answer_relevancy", "precision_with_ref", "precision_without_ref",
        "context_recall", "answer_correctness",
    )
    metrics = {n: _Metric(overrides.get(n, 0.8)) for n in names}
    return RagasScorer(**metrics), metrics  # type: ignore[arg-type]


async def test_scorer_picks_metrics_by_available_reference() -> None:
    scorer, metrics = _scorer()
    with_ref = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference="r", answered=True)
    )
    assert set(with_ref) == {
        "context_precision", "context_recall", "faithfulness", "answer_relevancy",
        "answer_correctness",
    }
    assert metrics["precision_without_ref"].calls == []

    scorer, metrics = _scorer()
    no_ref = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference=None, answered=True)
    )
    assert set(no_ref) == {"context_precision", "faithfulness", "answer_relevancy"}
    assert metrics["precision_with_ref"].calls == []

    scorer, _ = _scorer()
    refused = await scorer.score(
        ScoreInput(question="q", answer="", contexts=[], reference="r", answered=False)
    )
    assert refused == {}


async def test_scorer_failed_metric_is_none() -> None:
    scorer, _ = _scorer(faithfulness=RuntimeError("judge down"))
    scores = await scorer.score(
        ScoreInput(question="q", answer="a", contexts=["c"], reference=None, answered=True)
    )
    assert scores["faithfulness"] is None
    assert scores["answer_relevancy"] == 0.8


def test_build_ragas_scorer_offline() -> None:
    settings = Settings(_env_file=None, jwt_secret="x" * 40, openai_api_key="sk-test")
    assert isinstance(build_ragas_scorer(settings, "gpt-5-mini"), RagasScorer)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_eval_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'answer_once'`

- [ ] **Step 4: Implement**

`backend/app/chat/answer.py`:
- Add `contexts: list[str] = field(default_factory=list)` to `_Result`.
- In `_run`, right after `chunks = await retrieve(...)`, set `result.contexts = [c.text for c in chunks]`.
- At the end of the module add:

```python
PipelineResult = _Result
Usage = _Usage


async def answer_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    config: RagConfig,
    *,
    user: User,
    question: str,
    collection_ids: Sequence[uuid.UUID] = (),
) -> tuple[_Result, _Usage]:
    """Run the full pipeline (guardrails included) once and save nothing: for evaluation.
    `user` may be a transient User; only its groups are used. Exceptions propagate."""
    async with sessionmaker() as session:
        visible = await visible_collections(session, user)
    wanted = set(collection_ids)
    sensitive_scope = any(c.sensitive for c in visible if not wanted or c.id in wanted)
    usage, result = _Usage(), _Result(standalone=question)
    async for _ in _run(
        deps,
        sessionmaker,
        config,
        user=user,
        question=question,
        collection_ids=collection_ids,
        history=[],
        sensitive_scope=sensitive_scope,
        usage=usage,
        result=result,
    ):
        pass
    return result, usage
```

`backend/app/chat/wiring.py`: move `_chat_deps` from `main.py` here unchanged as `build_chat_deps(settings: Settings, index: ChunkIndex) -> ChatDeps`, keeping its docstring and lazy caches. Then in `main.py` import it and call `build_chat_deps(settings, app.state.index)`, and delete the now-unused imports there.

`backend/app/llm/rag_config.py` — add to `RagConfig` after `fallback_model`:

```python
    eval_judge_model: str = Field(default="gpt-5-mini", min_length=1, max_length=100)
```

(Evaluation judging isn't metered against cost caps, so the prices validator does not need it.)

`backend/app/evaluation/scoring.py`:

```python
"""Answer-quality scoring with Ragas (spec §7.1), behind a small protocol so tests use fakes.
A metric that fails returns None for that case; the run continues."""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)

METRICS = (
    "hit_rate",
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
    "answer_correctness",
)


@dataclass(frozen=True)
class ScoreInput:
    question: str
    answer: str
    contexts: list[str]
    reference: str | None  # the expected answer, if the case has one
    answered: bool  # an actual answer was generated


class Scorer(Protocol):
    async def score(self, item: ScoreInput) -> dict[str, float | None]: ...


class RagasScorer:
    def __init__(
        self,
        *,
        faithfulness: Any,
        answer_relevancy: Any,
        precision_with_ref: Any,
        precision_without_ref: Any,
        context_recall: Any,
        answer_correctness: Any,
    ) -> None:
        self.faithfulness = faithfulness
        self.answer_relevancy = answer_relevancy
        self.precision_with_ref = precision_with_ref
        self.precision_without_ref = precision_without_ref
        self.context_recall = context_recall
        self.answer_correctness = answer_correctness

    async def score(self, item: ScoreInput) -> dict[str, float | None]:
        jobs: dict[str, Awaitable[Any]] = {}
        q, a, ctx, ref = item.question, item.answer, item.contexts, item.reference
        if ctx and ref:
            jobs["context_precision"] = self.precision_with_ref.ascore(
                user_input=q, reference=ref, retrieved_contexts=ctx
            )
            jobs["context_recall"] = self.context_recall.ascore(
                user_input=q, retrieved_contexts=ctx, reference=ref
            )
        if item.answered:
            if ctx and not ref:
                jobs["context_precision"] = self.precision_without_ref.ascore(
                    user_input=q, response=a, retrieved_contexts=ctx
                )
            if ctx:
                jobs["faithfulness"] = self.faithfulness.ascore(
                    user_input=q, response=a, retrieved_contexts=ctx
                )
            jobs["answer_relevancy"] = self.answer_relevancy.ascore(user_input=q, response=a)
            if ref:
                jobs["answer_correctness"] = self.answer_correctness.ascore(
                    user_input=q, response=a, reference=ref
                )
        names = list(jobs)
        outcomes = await asyncio.gather(*jobs.values(), return_exceptions=True)
        scores: dict[str, float | None] = {}
        for name, outcome in zip(names, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning("Metric %s failed: %s", name, outcome)
                scores[name] = None
            else:
                scores[name] = float(outcome.value)
        return scores


def build_ragas_scorer(settings: Settings, judge_model: str) -> RagasScorer:
    """Real Ragas metrics judged by `judge_model` (OpenAI). Built offline; calls happen later."""
    from openai import AsyncOpenAI
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    if settings.openai_api_key is None:
        raise RuntimeError("RAG_OPENAI_API_KEY is not set")
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(), max_retries=2, timeout=120
    )
    llm = llm_factory(judge_model, provider="openai", client=client)
    embeddings = OpenAIEmbeddings(client=client, model=settings.embedding_model)
    return RagasScorer(
        faithfulness=Faithfulness(llm=llm),
        answer_relevancy=AnswerRelevancy(llm=llm, embeddings=embeddings),
        precision_with_ref=ContextPrecisionWithReference(llm=llm),
        precision_without_ref=ContextPrecisionWithoutReference(llm=llm),
        context_recall=ContextRecall(llm=llm),
        answer_correctness=AnswerCorrectness(llm=llm, embeddings=embeddings),
    )
```

Check the constructor keyword names of `ContextPrecisionWithReference` and `ContextPrecisionWithoutReference` with `inspect.signature`, and adapt if they differ. The GPT-5 family rejects non-default `temperature`. If `llm_factory` sets one, pass the accepted value through its `**kwargs` (for example `temperature=1`). The Task 5 e2e is where this is verified for real.

`backend/app/evaluation/runner.py`:

```python
"""Runs one eval case through the real pipeline as a transient user with the case's run-as
groups, and computes the metrics that need no judge (hit rate, "I don't know" accuracy)."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.answer import ChatDeps, answer_once
from app.core.tracing import answer_span
from app.evaluation.models import EvalCase
from app.llm.rag_config import RagConfig, compute_cost
from app.users.models import Group, User

logger = logging.getLogger(__name__)


@dataclass
class CaseOutcome:
    outcome: str
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    trace_id: str | None = None
    error: str | None = None


def is_refusal(outcome: str, citations: list[dict[str, Any]]) -> bool:
    """'I don't know': nothing found, or an answer that cites no source."""
    return outcome == "not_found" or (outcome == "answered" and not citations)


def deterministic_metrics(case: EvalCase, outcome: Any) -> dict[str, float | None]:
    hit_rate: float | None = None
    if case.expected_sources:
        found = {(s.get("doc_id"), s.get("page")) for s in outcome.sources}
        found_docs = {doc for doc, _ in found}
        hit = any(
            (e["doc_id"], e["page"]) in found if e.get("page") else e["doc_id"] in found_docs
            for e in case.expected_sources
        )
        hit_rate = 1.0 if hit else 0.0
    idk_correct: float | None = None
    if outcome.outcome != "error":
        idk_correct = 1.0 if is_refusal(outcome.outcome, outcome.citations) == case.unanswerable else 0.0
    return {"hit_rate": hit_rate, "idk_correct": idk_correct}


async def run_case(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    config: RagConfig,
    case: EvalCase,
    groups: list[Group],
    *,
    run_id: uuid.UUID,
) -> CaseOutcome:
    # Transient: never added to a session, so nothing about it is stored.
    user = User(id=uuid.uuid4(), username="eval", full_name="Evaluation", role="user")
    user.groups = groups
    started = time.monotonic()
    with answer_span("eval.case") as trace_id:
        span = trace.get_current_span()
        span.set_attribute("eval.run_id", str(run_id))
        span.set_attribute("eval.case_id", str(case.id))
        try:
            result, usage = await answer_once(
                sessionmaker,
                deps,
                config,
                user=user,
                question=case.question,
                collection_ids=[uuid.UUID(c) for c in case.collection_ids],
            )
        except Exception as exc:
            logger.exception("Eval case %s failed", case.id)
            return CaseOutcome(
                outcome="error",
                latency_ms=int((time.monotonic() - started) * 1000),
                trace_id=trace_id,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
    return CaseOutcome(
        outcome=result.outcome,
        answer=result.content,
        sources=result.sources,
        citations=result.citations,
        contexts=result.contexts if result.outcome == "answered" else [],
        latency_ms=int((time.monotonic() - started) * 1000),
        cost_usd=compute_cost(config, usage.tokens),
        input_tokens=sum(t[0] for t in usage.tokens.values()),
        output_tokens=sum(t[1] for t in usage.tokens.values()),
        trace_id=trace_id,
    )
```

Note on `contexts`: they are passed to the scorer only for `answered` outcomes, which is what `test_run_case_respects_run_as_groups` expects for the outsider (`not_found` → `[]`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_eval_runner.py tests/test_chat_answer.py tests/test_chat_guardrails.py tests/test_chat_api.py -v`
Expected: PASS. The last three confirm the `answer.py` / `main.py` refactor broke nothing.

- [ ] **Step 6: Full suite, lint, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add backend
git commit -m "feat(evaluation): non-persisting pipeline run, case runner and ragas scoring"
```

---

### Task 4: Eval runs — execution, summary, compare, Celery task, API, activation warning

**Files:**
- Create: `backend/app/evaluation/runs.py`, `backend/app/evaluation/tasks.py`, `backend/app/worker.py`, `backend/tests/test_eval_runs.py`
- Modify: `backend/app/evaluation/schemas.py`, `backend/app/api/admin_evaluation.py`, `backend/app/api/admin_rag_config.py`, `backend/app/llm/rag_config.py`, `backend/app/main.py`, `backend/tests/conftest.py`, `deploy/docker-compose.yml`

**Interfaces:**
- Consumes:
  - Task 1: `EvalSet`, `EvalCase`, `EvalRun`, `EvalResult`, `get_set`, `NotFound`, `InvalidCase`.
  - Task 3: `run_case`, `deterministic_metrics`, `ScoreInput`, `Scorer`, `build_ragas_scorer`, `METRICS`, `build_chat_deps`.
  - Plan 2: `RagConfigVersion`, `get_active`, `celery_app`.
- Produces:
  - `runs.create_run(session, actor, eval_set_id, rag_config_id=None) -> EvalRun`;
  - `runs.execute_run(run_id, *, sessionmaker, deps, scorer_factory, concurrency=4) -> None`, where `scorer_factory: Callable[[str], Scorer]` takes the judge model name;
  - `runs.summarize(results) -> dict`; `runs.compare(session, a_id, b_id) -> dict`; `runs.latest_scores(session, rag_config_ids) -> dict[uuid.UUID, dict]`.
  - `tasks.enqueue_eval(run_id)`; `app.state.enqueue_eval`.
  - Routes:
    - `POST /api/admin/eval-runs` → 202
    - `GET /api/admin/eval-runs?eval_set_id=`
    - `GET /api/admin/eval-runs/compare?a=&b=`
    - `GET /api/admin/eval-runs/{run_id}`
  - `RagConfigVersionOut.latest_eval`.

- [ ] **Step 1: Test wiring** — in `backend/tests/conftest.py`'s `app` fixture, add a list fixture like `enqueued`:

```python
@pytest.fixture
def enqueued_evals() -> list[UUID]:
    return []
```

Add `enqueued_evals: list[UUID]` to the `app` fixture's parameters and `application.state.enqueue_eval = enqueued_evals.append` next to `enqueue`.

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_eval_runs.py`

```python
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import create_sessionmaker
from app.evaluation import runs
from app.evaluation.models import EvalCase, EvalResult, EvalRun, EvalSet
from app.evaluation.scoring import ScoreInput
from app.ingestion.index import ChunkIndex
from app.llm import rag_config
from app.llm.rag_config import RagConfig
from app.users.models import Role
from tests.factories import (
    bearer,
    chat_deps,
    login,
    make_collection,
    make_group,
    make_user,
    seed_document,
)


class FakeScorer:
    def __init__(self, value: float = 0.9) -> None:
        self.value = value
        self.items: list[ScoreInput] = []

    async def score(self, item: ScoreInput) -> dict[str, float | None]:
        self.items.append(item)
        return {"faithfulness": self.value} if item.answered else {}


async def _set(session: AsyncSession, index: ChunkIndex) -> tuple[EvalSet, list[EvalCase]]:
    hr = await make_group(session, "hr")
    coll = await make_collection(session, "HR", [hr])
    doc = await seed_document(session, index, coll, ["Annual leave is 25 days per year."])
    eval_set = EvalSet(name="HR")
    session.add(eval_set)
    await session.flush()
    cases = [
        EvalCase(
            eval_set_id=eval_set.id,
            question="How many leave days?",
            expected_answer="25 days",
            expected_sources=[{"doc_id": str(doc.id), "page": 1}],
            run_as_group_ids=[str(hr.id)],
        ),
        EvalCase(
            eval_set_id=eval_set.id,
            question="What is the CEO's salary?",
            unanswerable=True,
            run_as_group_ids=[str(hr.id)],
        ),
    ]
    session.add_all(cases)
    await session.commit()
    return eval_set, cases


async def _execute(engine: AsyncEngine, run: EvalRun, deps, scorer: FakeScorer) -> None:
    await runs.execute_run(
        run.id, sessionmaker=create_sessionmaker(engine), deps=deps,
        scorer_factory=lambda judge: scorer,
    )


async def test_run_executes_scores_and_summarizes(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()
    assert (run.status, run.case_count, run.rag_config_version) == ("queued", 2, None)

    async def low_for_salary(model: str, query: str, docs: list[str]) -> list[float]:
        return [0.01 if "salary" in query else 0.9 for _ in docs]

    scorer = FakeScorer()
    await _execute(engine, run, chat_deps(chunk_index, rerank=low_for_salary), scorer)
    await session.refresh(run)
    assert run.status == "completed" and run.finished_at is not None
    results = (
        await session.scalars(select(EvalResult).where(EvalResult.run_id == run.id))
    ).all()
    by_question = {r.question: r for r in results}
    leave = by_question["How many leave days?"]
    assert leave.outcome == "answered"
    assert leave.metrics["hit_rate"] == 1.0 and leave.metrics["idk_correct"] == 1.0
    assert leave.metrics["faithfulness"] == 0.9
    salary = by_question["What is the CEO's salary?"]
    assert salary.outcome == "not_found" and salary.metrics["idk_correct"] == 1.0
    summary = run.summary
    assert summary["cases"] == 2 and summary["errors"] == 0
    assert summary["idk_accuracy"] == 1.0 and summary["metrics"]["faithfulness"] == 0.9
    assert summary["metrics"]["hit_rate"] == 1.0
    assert summary["latency_p50_ms"] >= 0 and "score" in summary
    # Both non-error cases reach the scorer; only the answered one gets answer metrics.
    assert [i.reference for i in scorer.items if i.answered] == ["25 days"]


async def test_failing_case_is_recorded_and_run_completes(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    boss = await make_user(session, username="boss", role=Role.ADMIN)
    run = await runs.create_run(session, boss, eval_set.id)
    await session.commit()

    async def broken_embed(text: str) -> list[float]:
        if "salary" in text:
            raise RuntimeError("embedding service down")
        return [1.0] * 8

    deps = chat_deps(chunk_index)
    deps.retrieval.embed_query = broken_embed
    await _execute(engine, run, deps, FakeScorer())
    await session.refresh(run)
    assert run.status == "completed" and run.summary["errors"] == 1
    failed = await session.scalar(
        select(EvalResult).where(EvalResult.run_id == run.id, EvalResult.outcome == "error")
    )
    assert failed is not None and "embedding service down" in (failed.error or "")


async def test_run_uses_the_chosen_config_and_compare_flags_regressions(
    engine: AsyncEngine, session: AsyncSession, chunk_index: ChunkIndex
) -> None:
    eval_set, _ = await _set(session, chunk_index)
    root = await make_user(session, username="root", role=Role.SUPER_ADMIN)
    strict = await rag_config.create_version(session, root, RagConfig(rerank_threshold=0.99))
    await session.commit()

    good = await runs.create_run(session, root, eval_set.id)
    bad = await runs.create_run(session, root, eval_set.id, rag_config_id=strict.id)
    await session.commit()
    assert bad.rag_config_version == strict.version
    for run in (good, bad):
        await _execute(engine, run, chat_deps(chunk_index), FakeScorer())

    report = await runs.compare(session, good.id, bad.id)
    leave = next(q for q in report["questions"] if q["question"] == "How many leave days?")
    assert leave["a"]["outcome"] == "answered" and leave["b"]["outcome"] == "not_found"
    assert leave["regressed"] is True
    assert "hit_rate" in " ".join(leave["reasons"]) or "idk_correct" in " ".join(leave["reasons"])
    assert report["deltas"]["idk_accuracy"] < 0

    latest = await runs.latest_scores(session, [strict.id])
    assert latest[strict.id]["run_id"] == str(bad.id)


async def test_runs_api(app: FastAPI, client: AsyncClient, session: AsyncSession,
                        enqueued_evals: list[uuid.UUID]) -> None:
    eval_set, _ = await _set(session, app.state.index)
    await make_user(session, username="root", role=Role.SUPER_ADMIN)
    h = bearer(await login(client, "root"))

    created = await client.post(
        "/api/admin/eval-runs", headers=h, json={"eval_set_id": str(eval_set.id)}
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    assert enqueued_evals == [uuid.UUID(run_id)]
    listed = await client.get(
        "/api/admin/eval-runs", headers=h, params={"eval_set_id": str(eval_set.id)}
    )
    assert [r["id"] for r in listed.json()] == [run_id]
    detail = await client.get(f"/api/admin/eval-runs/{run_id}", headers=h)
    assert detail.json()["status"] == "queued" and detail.json()["results"] == []

    empty = EvalSet(name="Empty")
    session.add(empty)
    await session.commit()
    rejected = await client.post(
        "/api/admin/eval-runs", headers=h, json={"eval_set_id": str(empty.id)}
    )
    assert rejected.status_code == 422

    run = await session.get(EvalRun, uuid.UUID(run_id))
    assert run is not None
    run.status, run.summary = "completed", {"score": 0.7}
    await session.commit()
    configs = (await client.get("/api/admin/rag-configs", headers=h)).json()
    assert configs == []  # no versions yet; latest_eval is attached per version when present
```

The final assertion in `test_runs_api` only proves the endpoint still works with no versions. The real latest-eval attachment is asserted through `runs.latest_scores` in the compare test and in Step 4's route code. Keep it as written.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_eval_runs.py -v`
Expected: FAIL with `ImportError: cannot import name 'runs'`

- [ ] **Step 4: Implement**

`backend/app/evaluation/schemas.py` — append:

```python
class RunIn(BaseModel):
    eval_set_id: uuid.UUID
    rag_config_id: uuid.UUID | None = None  # None: the active version (or defaults)


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    eval_set_id: uuid.UUID
    rag_config_id: uuid.UUID | None
    rag_config_version: int | None
    status: str
    error: str | None
    case_count: int
    summary: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvalResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID | None
    question: str
    unanswerable: bool
    outcome: str
    answer: str
    sources: list[dict[str, Any]]
    metrics: dict[str, Any]
    latency_ms: int
    cost_usd: float
    trace_id: str | None
    error: str | None


class EvalRunDetail(EvalRunOut):
    results: list[EvalResultOut]
```

`backend/app/evaluation/runs.py`:

```python
"""Eval runs: create (queued), execute in the worker, summarize, compare (spec §7.1)."""

import asyncio
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import service as audit
from app.chat.answer import ChatDeps
from app.evaluation import service
from app.evaluation.models import EvalCase, EvalResult, EvalRun
from app.evaluation.runner import deterministic_metrics, run_case
from app.evaluation.scoring import METRICS, ScoreInput, Scorer
from app.llm.models import RagConfigVersion
from app.llm.rag_config import RagConfig, get_active
from app.users.models import Group, User

logger = logging.getLogger(__name__)
REGRESSION_DROP = 0.1


async def create_run(
    session: AsyncSession,
    actor: User,
    eval_set_id: uuid.UUID,
    rag_config_id: uuid.UUID | None = None,
) -> EvalRun:
    eval_set = await service.get_set(session, eval_set_id)
    cases = await service.list_cases(session, eval_set.id)
    if not cases:
        raise service.InvalidCase("This eval set has no cases")
    if rag_config_id is not None:
        row = await session.get(RagConfigVersion, rag_config_id)
        if row is None:
            raise service.NotFound("RAG config version not found")
        version, config = row.version, RagConfig.model_validate(row.data)
    else:
        version, config = await get_active(session)
        row = (
            await session.scalar(
                select(RagConfigVersion).where(RagConfigVersion.version == version)
            )
            if version is not None
            else None
        )
    run = EvalRun(
        eval_set_id=eval_set.id,
        rag_config_id=row.id if row is not None else None,
        rag_config_version=version,
        config=config.model_dump(mode="json"),
        case_count=len(cases),
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    await audit.record(
        session, action="eval_run.created", actor=actor, target_type="eval_run",
        target_id=run.id, detail={"eval_set_id": str(eval_set.id), "rag_config_version": version},
    )
    return run


def _percentile(values: Sequence[int], fraction: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return int(ordered[index])


def summarize(results: Sequence[EvalResult]) -> dict[str, Any]:
    metric_means: dict[str, float] = {}
    for name in METRICS:
        values = [r.metrics.get(name) for r in results if r.metrics.get(name) is not None]
        if values:
            metric_means[name] = round(mean(float(v) for v in values), 4)
    idk = [r.metrics.get("idk_correct") for r in results if r.metrics.get("idk_correct") is not None]
    idk_accuracy = round(mean(float(v) for v in idk), 4) if idk else None
    parts = list(metric_means.values()) + ([idk_accuracy] if idk_accuracy is not None else [])
    outcomes: dict[str, int] = {}
    for r in results:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    latencies = [r.latency_ms for r in results]
    return {
        "cases": len(results),
        "errors": outcomes.get("error", 0),
        "outcomes": outcomes,
        "metrics": metric_means,
        "idk_accuracy": idk_accuracy,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cost_per_question_usd": round(mean(r.cost_usd for r in results), 6) if results else 0.0,
        "score": round(mean(parts), 4) if parts else None,
    }


async def _load(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> tuple[EvalRun, list[EvalCase], dict[str, Group]]:
    async with sessionmaker() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            raise service.NotFound(f"Eval run {run_id} not found")
        cases = list(
            (
                await session.scalars(
                    select(EvalCase)
                    .where(EvalCase.eval_set_id == run.eval_set_id)
                    .order_by(EvalCase.seq)
                )
            ).all()
        )
        group_ids = {uuid.UUID(g) for c in cases for g in c.run_as_group_ids}
        groups = (
            (await session.scalars(select(Group).where(Group.id.in_(group_ids)))).all()
            if group_ids
            else []
        )
        await session.execute(delete(EvalResult).where(EvalResult.run_id == run_id))  # re-run
        run.status, run.started_at, run.error = "running", datetime.now(UTC), None
        await session.commit()
        return run, cases, {str(g.id): g for g in groups}


async def execute_run(
    run_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: ChatDeps,
    scorer_factory: Callable[[str], Scorer],
    concurrency: int = 4,
) -> None:
    """Run every case of the run's eval set and store results and a summary. A case that fails
    is recorded as an error; only an infrastructure failure marks the whole run failed."""
    run, cases, groups = await _load(sessionmaker, run_id)
    try:
        config = RagConfig.model_validate(run.config)
        scorer = scorer_factory(config.eval_judge_model)
        limit = asyncio.Semaphore(concurrency)

        async def one(case: EvalCase) -> None:
            async with limit:
                case_groups = [groups[g] for g in case.run_as_group_ids if g in groups]
                outcome = await run_case(
                    sessionmaker, deps, config, case, case_groups, run_id=run.id
                )
                metrics: dict[str, Any] = deterministic_metrics(case, outcome)
                if outcome.outcome != "error":
                    metrics |= await scorer.score(
                        ScoreInput(
                            question=case.question,
                            answer=outcome.answer,
                            contexts=outcome.contexts,
                            reference=case.expected_answer,
                            answered=outcome.outcome == "answered",
                        )
                    )
                async with sessionmaker() as session:
                    session.add(
                        EvalResult(
                            run_id=run.id,
                            case_id=case.id,
                            case_seq=case.seq,
                            question=case.question,
                            unanswerable=case.unanswerable,
                            outcome=outcome.outcome,
                            answer=outcome.answer,
                            sources=outcome.sources,
                            metrics=metrics,
                            latency_ms=outcome.latency_ms,
                            cost_usd=outcome.cost_usd,
                            trace_id=outcome.trace_id,
                            error=outcome.error,
                        )
                    )
                    await session.commit()

        await asyncio.gather(*(one(case) for case in cases))
        async with sessionmaker() as session:
            stored = await session.get(EvalRun, run.id)
            assert stored is not None
            results = (
                await session.scalars(select(EvalResult).where(EvalResult.run_id == run.id))
            ).all()
            stored.summary = summarize(results)
            stored.status, stored.finished_at = "completed", datetime.now(UTC)
            await session.commit()
    except Exception as exc:
        logger.exception("Eval run %s failed", run_id)
        async with sessionmaker() as session:
            stored = await session.get(EvalRun, run_id)
            if stored is not None:
                stored.status, stored.finished_at = "failed", datetime.now(UTC)
                stored.error = f"{type(exc).__name__}: {exc}"[:1000]
                await session.commit()


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> tuple[EvalRun, list[EvalResult]]:
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise service.NotFound("Eval run not found")
    results = (
        await session.scalars(
            select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.case_seq)
        )
    ).all()
    return run, list(results)


async def list_runs(session: AsyncSession, eval_set_id: uuid.UUID | None = None) -> list[EvalRun]:
    query = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(200)
    if eval_set_id is not None:
        query = query.where(EvalRun.eval_set_id == eval_set_id)
    return list((await session.scalars(query)).all())


def _regression(a: EvalResult, b: EvalResult) -> list[str]:
    reasons = []
    if b.outcome == "error" and a.outcome != "error":
        reasons.append("now errors")
    for name in (*METRICS, "idk_correct"):
        before, after = a.metrics.get(name), b.metrics.get(name)
        if before is not None and after is not None and before - after >= REGRESSION_DROP:
            reasons.append(f"{name} {before:.2f} → {after:.2f}")
    return reasons


async def compare(session: AsyncSession, a_id: uuid.UUID, b_id: uuid.UUID) -> dict[str, Any]:
    run_a, results_a = await get_run(session, a_id)
    run_b, results_b = await get_run(session, b_id)
    by_case_b = {r.case_id: r for r in results_b if r.case_id is not None}
    questions = []
    for a in results_a:
        b = by_case_b.get(a.case_id) if a.case_id is not None else None
        if b is None:
            continue
        reasons = _regression(a, b)
        questions.append(
            {
                "case_id": str(a.case_id),
                "question": a.question,
                "a": {"outcome": a.outcome, "metrics": a.metrics, "answer": a.answer},
                "b": {"outcome": b.outcome, "metrics": b.metrics, "answer": b.answer},
                "regressed": bool(reasons),
                "reasons": reasons,
            }
        )
    keys = set(run_a.summary.get("metrics", {})) | set(run_b.summary.get("metrics", {}))
    deltas = {
        k: round(run_b.summary["metrics"][k] - run_a.summary["metrics"][k], 4)
        for k in keys
        if k in run_a.summary.get("metrics", {}) and k in run_b.summary.get("metrics", {})
    }
    for k in ("idk_accuracy", "score", "latency_p95_ms", "cost_per_question_usd"):
        if run_a.summary.get(k) is not None and run_b.summary.get(k) is not None:
            deltas[k] = round(run_b.summary[k] - run_a.summary[k], 6)
    return {
        "a": {"id": str(run_a.id), "summary": run_a.summary},
        "b": {"id": str(run_b.id), "summary": run_b.summary},
        "deltas": deltas,
        "questions": questions,
    }


async def latest_scores(
    session: AsyncSession, rag_config_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Latest completed eval run per config version (spec §7.1 activation warning)."""
    if not rag_config_ids:
        return {}
    query = (
        select(EvalRun)
        .where(EvalRun.rag_config_id.in_(rag_config_ids), EvalRun.status == "completed")
        .order_by(EvalRun.finished_at.desc())
    )
    latest: dict[uuid.UUID, dict[str, Any]] = {}
    for run in (await session.scalars(query)).all():
        if run.rag_config_id is not None and run.rag_config_id not in latest:
            latest[run.rag_config_id] = {
                "run_id": str(run.id),
                "eval_set_id": str(run.eval_set_id),
                "score": run.summary.get("score"),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
    return latest
```

`backend/app/evaluation/tasks.py`:

```python
"""Celery task for eval runs, on its own queue so long runs never delay ingestion."""

import asyncio
import uuid

from qdrant_client import AsyncQdrantClient

from app.chat.wiring import build_chat_deps
from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.tracing import setup_tracing
from app.evaluation.runs import execute_run
from app.evaluation.scoring import build_ragas_scorer
from app.ingestion.index import ChunkIndex
from app.ingestion.tasks import celery_app

EVAL_QUEUE = "evaluation"


async def _run(run_id: uuid.UUID) -> None:
    settings = get_settings()
    setup_tracing(settings)  # eval.case spans go to Phoenix when configured
    engine = create_engine(settings.database_url)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimensions)
        await execute_run(
            run_id,
            sessionmaker=create_sessionmaker(engine),
            deps=build_chat_deps(settings, index),
            scorer_factory=lambda judge: build_ragas_scorer(settings, judge),
        )
    finally:
        await qdrant.close()
        await engine.dispose()


@celery_app.task(name="evaluation.run_eval")
def run_eval(run_id: str) -> None:
    asyncio.run(_run(uuid.UUID(run_id)))


def enqueue_eval(run_id: uuid.UUID) -> None:
    run_eval.apply_async(args=[str(run_id)], queue=EVAL_QUEUE)
```

`backend/app/worker.py`:

```python
"""Celery worker entry point for every queue:
celery -A app.worker worker -Q ingestion,evaluation"""

import app.evaluation.tasks  # noqa: F401  (registers evaluation tasks)
from app.ingestion.tasks import celery_app

__all__ = ["celery_app"]
```

`backend/app/main.py` — next to `_enqueue_with_celery`:

```python
def _enqueue_eval_with_celery(run_id: uuid.UUID) -> None:
    from app.evaluation.tasks import enqueue_eval  # imported lazily: Celery + Ragas

    enqueue_eval(run_id)
```

and `app.state.enqueue_eval = _enqueue_eval_with_celery`.

`backend/app/api/admin_evaluation.py` — add (imports: `Request`, `runs`, `RunIn`, `EvalRunOut`, `EvalRunDetail`, `EvalResultOut`, `logging`):

```python
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
    try:
        run, results = await runs.get_run(session, run_id)
    except service.EvaluationError as exc:
        raise _http_error(exc) from None
    return EvalRunDetail(
        **EvalRunOut.model_validate(run).model_dump(),
        results=[EvalResultOut.model_validate(r) for r in results],
    )
```

`/eval-runs/compare` must be declared before `/eval-runs/{run_id}`.

`backend/app/llm/rag_config.py` — add `latest_eval: dict[str, Any] | None = None` to `RagConfigVersionOut`, and add `Any` to the typing import.

`backend/app/api/admin_rag_config.py` — in `list_versions` and `get_active`, attach the latest eval (import `from app.evaluation import runs as eval_runs`):

```python
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
```

and add `latest_eval: dict[str, Any] | None = None` to `ActiveConfigOut`, filled the same way for the active row when one exists.

`deploy/docker-compose.yml` — worker command:

```yaml
    command: ["celery", "-A", "app.worker", "worker", "-Q", "ingestion,evaluation", "--concurrency=2", "--loglevel=INFO"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_eval_runs.py tests/test_rag_config.py tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 6: Full suite, lint, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

```bash
git add backend deploy/docker-compose.yml
git commit -m "feat(evaluation): eval runs in a celery job with ragas scores, compare and latest score per config"
```

---

### Task 5: End-to-end check on the real stack

**Files:** nothing is expected to change, unless the e2e exposes a bug (report it, don't patch).

- [ ] **Step 1: Build and start**

`deploy/.env` already has `RAG_OPENAI_API_KEY`; never print or commit it.

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```
Expected: `api` is healthy, migrations reach `0007`, and the `worker` log shows it consuming `ingestion,evaluation`.

- [ ] **Step 2: Set up data.** Use the Plan 3/4 e2e setup: create root, the `e2e` group (root added to it) and the `E2E` collection, then upload `e2e.pdf` ("Annual leave is twenty days per year") and wait for `ready`.

- [ ] **Step 3: Eval set by CSV, two runs, compare**

```bash
printf 'question,expected_answer,collections,groups,unanswerable\nHow many days of annual leave do employees get?,Twenty days per year,E2E,e2e,false\nWhat is the CEO salary?,,E2E,e2e,true\n' > cases.csv
SET=$(curl -s -X POST $API/admin/eval-sets -H "$H" -H "Content-Type: application/json" -d '{"name":"E2E set"}' | eval $J id)
curl -s -X POST $API/admin/eval-sets/$SET/import -H "$H" -F "file=@cases.csv"
STRICT=$(curl -s -X POST $API/admin/rag-configs -H "$H" -H "Content-Type: application/json" -d '{"config":{"rerank_threshold":0.999}}' | eval $J id)
A=$(curl -s -X POST $API/admin/eval-runs -H "$H" -H "Content-Type: application/json" -d "{\"eval_set_id\":\"$SET\"}" | eval $J id)
B=$(curl -s -X POST $API/admin/eval-runs -H "$H" -H "Content-Type: application/json" -d "{\"eval_set_id\":\"$SET\",\"rag_config_id\":\"$STRICT\"}" | eval $J id)
```
Poll `GET $API/admin/eval-runs/$A` and `$B` until `status` is `completed` (or `failed`, in which case report `error`). Then:

```bash
curl -s "$API/admin/eval-runs/compare?a=$A&b=$B" -H "$H" | python -m json.tool | head -60
curl -s $API/admin/rag-configs -H "$H" | python -m json.tool | grep -A5 latest_eval
```
Expected:
- the import reports `"created": 2`;
- run A answers the leave question, with `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall` and `answer_correctness` all present as numbers, `hit_rate` null (no expected sources), and `idk_correct` 1.0 on both cases;
- run B returns `not_found` for the leave question, and compare marks it `regressed`;
- the strict version shows `latest_eval` with a score.

If Ragas metrics are all `null`, check the worker logs for the metric warnings (for example a temperature or model error from the judge). Report the exact error rather than changing code.

- [ ] **Step 4: Review queue**

Ask a question as root (`POST $API/chat`), give it 👎 (`POST $API/messages/<id>/feedback {"rating":-1}`), then:

```bash
curl -s $API/admin/review-queue -H "$H" | python -m json.tool | head -30
curl -s $API/admin/review-queue/messages/<message_id> -H "$H" | python -m json.tool | head -20
curl -s -X POST $API/admin/review-queue/messages/<message_id>/add-to-eval-set -H "$H" -H "Content-Type: application/json" -d "{\"eval_set_id\":\"$SET\",\"expected_answer\":\"Twenty days\"}"
curl -s "$API/admin/audit" -H "$H" | python -m json.tool | grep -E '"review\.' | head
```
Expected:
- the 👎 item is listed;
- the detail view returns the question and answer;
- add-to-eval-set gives 201;
- the audit log contains `review.queue_viewed`, `review.message_viewed` and `review.added_to_eval_set`.

- [ ] **Step 5: Phoenix.** In http://127.0.0.1:6006, confirm `eval.case` spans carry `eval.run_id`. If you can't check this programmatically, say so.

- [ ] **Step 6: Clean up.** Run `rm e2e.pdf cases.csv` and `docker compose -f deploy/docker-compose.yml down -v`. No commit is needed unless something changed.

---

## Spec coverage for this plan

| Spec requirement | Task |
|---|---|
| §7.1 test sets: question, expected answer/sources, collection scope, run-as groups, unanswerable cases | 1 |
| §7.1 create cases manually, by CSV import, from the review queue | 1, 2 |
| §7.1 runs: test set + RagConfig version → Celery job → real pipeline (same permissions and guardrails) | 3, 4 |
| §7.1 Ragas metrics with the judge model: context precision/recall, faithfulness, answer relevance, correctness; hit rate@k; "I don't know" accuracy; latency p50/p95; cost per question | 3, 4 |
| §7.1 compare two runs per question with regressions highlighted | 4 |
| §7.1 / §4.2 activation warning: latest eval score per config version | 4 |
| §7.1 Phoenix: cases traced (tagged traces; full experiments deferred by user decision) | 3, 4 |
| §6.5 review queue: 👎, low-confidence, guardrail flags; one-click add to test set | 2 |
| §6.6 admin views of user conversations only via the review queue, audited | 2 |
| Plan 4 carry-ins: review queue over `guardrail_events`/`low_confidence`; pre-flight refusals recorded (rate-limited) | 2 |
