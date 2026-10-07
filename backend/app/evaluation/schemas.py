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
