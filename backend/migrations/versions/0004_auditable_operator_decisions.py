"""Add final operator assignments and terminal decision constraints.

Revision ID: 0004_auditable_decisions
Revises: 0003_snapshot_resource_overrides
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_auditable_decisions"
down_revision: str | None = "0003_snapshot_resource_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_decision_actions_recommendation",
        "decision_actions",
        ["recommendation_id"],
    )
    op.create_unique_constraint(
        "uq_audit_events_decision_action",
        "audit_events",
        ["decision_action_id"],
    )
    op.create_table(
        "decision_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "decision_action_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("destination_id", sa.String(length=255), nullable=False),
        sa.Column("route", postgresql.JSONB(), nullable=False),
        sa.Column("travel_minutes", sa.Float(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decision_action_id"],
            ["decision_actions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource_units.resource_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["exposed_assets.asset_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_action_id",
            "resource_id",
            name="uq_decision_assignments_decision_resource",
        ),
    )
    op.create_index(
        "uq_decision_assignments_active_resource",
        "decision_assignments",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_decision_assignments_active_resource",
        table_name="decision_assignments",
    )
    op.drop_table("decision_assignments")
    op.drop_constraint(
        "uq_audit_events_decision_action",
        "audit_events",
        type_="unique",
    )
    op.drop_constraint(
        "uq_decision_actions_recommendation",
        "decision_actions",
        type_="unique",
    )
