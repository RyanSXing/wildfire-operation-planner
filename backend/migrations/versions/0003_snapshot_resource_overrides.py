"""Detach pinned scenario overrides from live resources.

Revision ID: 0003_snapshot_resource_overrides
Revises: 0002_exposure_geography_idx
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0003_snapshot_resource_overrides"
down_revision: str | None = "0002_exposure_geography_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "scenario_resource_overrides_resource_id_fkey",
        "scenario_resource_overrides",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "scenario_resource_overrides_resource_id_fkey",
        "scenario_resource_overrides",
        "resource_units",
        ["resource_id"],
        ["resource_id"],
        ondelete="RESTRICT",
    )
