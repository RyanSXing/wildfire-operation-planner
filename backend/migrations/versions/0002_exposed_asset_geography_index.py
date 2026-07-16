"""Index exposed-asset geography distance queries.

Revision ID: 0002_exposure_geography_idx
Revises: 0001_operational_schema
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0002_exposure_geography_idx"
down_revision: str | None = "0001_operational_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_exposed_assets_geometry_geography "
        "ON exposed_assets USING gist ((geometry::geography))"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exposed_assets_geometry_geography",
        table_name="exposed_assets",
    )
