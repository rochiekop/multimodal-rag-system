import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    SmallInteger,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """One user question or assistant answer, with everything needed to audit and evaluate it."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
        CheckConstraint("feedback_rating IN (-1, 1)", name="feedback_rating_valid"),
    )
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))  # stable ordering
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    standalone_question: Mapped[str | None] = mapped_column(Text)
    collection_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # answered | not_found | small_talk | blocked | support | off_topic | error | cancelled
    outcome: Mapped[str | None] = mapped_column(String(20))
    low_confidence: Mapped[bool] = mapped_column(default=False, server_default=false())
    guardrail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # decisive check + flags
    top_score: Mapped[float | None]
    latency_ms: Mapped[int | None]
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    rag_config_version: Mapped[int | None]
    feedback_rating: Mapped[int | None] = mapped_column(SmallInteger)
    feedback_comment: Mapped[str | None] = mapped_column(String(2000))
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
