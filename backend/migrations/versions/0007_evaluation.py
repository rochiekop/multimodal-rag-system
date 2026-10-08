"""eval sets, cases, runs, results; review columns on messages and guardrail events

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _jsonb(name: str) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def upgrade() -> None:
    op.create_table(
        "eval_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _now("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_sets")),
        sa.UniqueConstraint("name", name=op.f("uq_eval_sets_name")),
    )
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("eval_set_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        _jsonb("expected_sources"),
        _jsonb("collection_ids"),
        _jsonb("run_as_group_ids"),
        sa.Column("unanswerable", sa.Boolean(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["eval_set_id"],
            ["eval_sets.id"],
            name=op.f("fk_eval_cases_eval_set_id_eval_sets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_eval_cases_source_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_cases")),
    )
    op.create_index(op.f("ix_eval_cases_eval_set_id"), "eval_cases", ["eval_set_id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_set_id", sa.Uuid(), nullable=False),
        sa.Column("rag_config_id", sa.Uuid(), nullable=True),
        sa.Column("rag_config_version", sa.Integer(), nullable=True),
        _jsonb("config"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False),
        _jsonb("summary"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _now("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["eval_set_id"],
            ["eval_sets.id"],
            name=op.f("fk_eval_runs_eval_set_id_eval_sets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rag_config_id"],
            ["rag_config_versions.id"],
            name=op.f("fk_eval_runs_rag_config_id_rag_config_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index(op.f("ix_eval_runs_eval_set_id"), "eval_runs", ["eval_set_id"])
    op.create_index(op.f("ix_eval_runs_rag_config_id"), "eval_runs", ["rag_config_id"])
    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("case_seq", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("unanswerable", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        _jsonb("sources"),
        _jsonb("metrics"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eval_runs.id"],
            name=op.f("fk_eval_results_run_id_eval_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["eval_cases.id"],
            name=op.f("fk_eval_results_case_id_eval_cases"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_results")),
        sa.UniqueConstraint("run_id", "case_id", name=op.f("uq_eval_results_run_id_case_id")),
    )
    op.create_index(op.f("ix_eval_results_run_id"), "eval_results", ["run_id"])
    op.add_column("messages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column(
        "guardrail_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("guardrail_events", sa.Column("reviewed_by", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("guardrail_events", "reviewed_by")
    op.drop_column("guardrail_events", "reviewed_at")
    op.drop_column("messages", "reviewed_by")
    op.drop_column("messages", "reviewed_at")
    op.drop_index(op.f("ix_eval_results_run_id"), table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index(op.f("ix_eval_runs_rag_config_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_eval_set_id"), table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index(op.f("ix_eval_cases_eval_set_id"), table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_table("eval_sets")
