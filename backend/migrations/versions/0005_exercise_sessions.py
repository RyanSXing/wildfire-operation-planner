"""Add isolated exercise sessions, plan runs, and events.

Revision ID: 0005_exercise_sessions
Revises: 0004_auditable_decisions
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_exercise_sessions"
down_revision: str | None = "0004_auditable_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exercise_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", sa.String(length=255), nullable=False),
        sa.Column("definition_version", sa.String(length=255), nullable=False),
        sa.Column("definition_digest", sa.String(length=64), nullable=False),
        sa.Column("callsign", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("checkpoint_index", sa.Integer(), nullable=False),
        sa.Column("objective", sa.String(length=80), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "consequences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'expired')",
            name="ck_exercise_sessions_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_exercise_sessions_version"),
        sa.CheckConstraint(
            "checkpoint_index BETWEEN 0 AND 2",
            name="ck_exercise_sessions_checkpoint",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_exercise_sessions_expiry",
        "exercise_sessions",
        ["status", "expires_at"],
    )
    op.create_table(
        "exercise_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "insertion_order",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_key", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "input_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "output_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["exercise_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_key_id"], ["idempotency_keys.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key_id", name="uq_exercise_plan_idempotency"),
    )
    op.create_index(
        "ix_exercise_plan_runs_session_checkpoint",
        "exercise_plan_runs",
        ["session_id", "checkpoint_key", "insertion_order"],
    )
    op.create_table(
        "exercise_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_callsign", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("expected_session_version", sa.Integer(), nullable=False),
        sa.Column("resulting_session_version", sa.Integer(), nullable=False),
        sa.Column(
            "before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["exercise_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "resulting_session_version",
            name="uq_exercise_event_session_version",
        ),
    )
    op.create_index(
        "ix_exercise_events_session_time",
        "exercise_events",
        ["session_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_exercise_events_session_time", table_name="exercise_events")
    op.drop_table("exercise_events")
    op.drop_index(
        "ix_exercise_plan_runs_session_checkpoint",
        table_name="exercise_plan_runs",
    )
    op.drop_table("exercise_plan_runs")
    op.drop_index("ix_exercise_sessions_expiry", table_name="exercise_sessions")
    op.drop_table("exercise_sessions")
