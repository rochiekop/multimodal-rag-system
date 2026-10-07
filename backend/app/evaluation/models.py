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
    status: Mapped[str] = mapped_column(
        String(20), default="queued"
    )  # queued|running|completed|failed
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
