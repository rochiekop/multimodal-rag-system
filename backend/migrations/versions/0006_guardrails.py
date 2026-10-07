"""guardrail events, notifications, usage records, chat lock, message guardrail fields

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("chat_locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("strike_reset_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "messages",
        sa.Column("low_confidence", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("guardrail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "guardrail_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("check", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("strike", sa.Boolean(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_guardrail_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_guardrail_events_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_guardrail_events_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guardrail_events")),
    )
    op.create_index(op.f("ix_guardrail_events_user_id"), "guardrail_events", ["user_id"])
    op.create_index(op.f("ix_guardrail_events_created_at"), "guardrail_events", ["created_at"])
    op.create_index(
        op.f("ix_guardrail_events_conversation_id"), "guardrail_events", ["conversation_id"]
    )
    op.create_index(op.f("ix_guardrail_events_message_id"), "guardrail_events", ["message_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        _now("created_at"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_dedupe_key")),
    )
    op.create_table(
        "usage_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_records_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_usage_records_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(op.f("ix_usage_records_user_id"), "usage_records", ["user_id"])
    op.create_index(op.f("ix_usage_records_created_at"), "usage_records", ["created_at"])
    op.create_index(op.f("ix_usage_records_message_id"), "usage_records", ["message_id"])
    op.create_index(
        op.f("ix_usage_records_user_id_created_at"), "usage_records", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_records_user_id_created_at"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_message_id"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_created_at"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_user_id"), table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_guardrail_events_message_id"), table_name="guardrail_events")
    op.drop_index(op.f("ix_guardrail_events_conversation_id"), table_name="guardrail_events")
    op.drop_index(op.f("ix_guardrail_events_created_at"), table_name="guardrail_events")
    op.drop_index(op.f("ix_guardrail_events_user_id"), table_name="guardrail_events")
    op.drop_table("guardrail_events")
    op.drop_column("messages", "guardrail")
    op.drop_column("messages", "low_confidence")
    op.drop_column("users", "strike_reset_at")
    op.drop_column("users", "chat_locked_until")
