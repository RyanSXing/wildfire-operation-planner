"""Create the WildfireOps operational schema.

Revision ID: 0001_operational_schema
Revises:
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_operational_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "source_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("observation_kind", sa.String(length=20), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("intensity", sa.Float(), nullable=True),
        sa.Column("wind_speed_mps", sa.Float(), nullable=True),
        sa.Column("wind_direction_degrees", sa.Float(), nullable=True),
        sa.Column("temperature_celsius", sa.Float(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "observation_kind IN ('fire', 'weather')",
            name="ck_source_observations_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_name",
            "source_record_id",
            name="uq_source_observations_source_identity",
        ),
    )
    op.create_index(
        "ix_source_observations_geometry",
        "source_observations",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "quarantined_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("validation_reason", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "quarantined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wildfire_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("severity_state", sa.String(length=40), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="GEOMETRY",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wildfire_incidents_geometry",
        "wildfire_incidents",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "incident_detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "observation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["wildfire_incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["source_observations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "incident_id",
            "observation_id",
            name="uq_incident_detections_membership",
        ),
    )

    op.create_table(
        "exposed_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False),
        sa.Column("asset_kind", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=100), nullable=True),
        sa.Column("source_version", sa.String(length=255), nullable=True),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="GEOMETRY",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id",
            name="uq_exposed_assets_asset_id",
        ),
    )
    op.create_index(
        "ix_exposed_assets_geometry",
        "exposed_assets",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "resource_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column(
            "available",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            name="uq_resource_units_resource_id",
        ),
    )
    op.create_index(
        "ix_resource_units_geometry",
        "resource_units",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "source_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column(
            "last_attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_success_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "accepted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "deduplicated_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "quarantined_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_name",
            name="uq_source_status_source_name",
        ),
    )

    op.create_table(
        "incident_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column(
            "source_versions",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("incident_state", postgresql.JSONB(), nullable=False),
        sa.Column(
            "asset_state",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "resource_state",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["wildfire_incidents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "incident_id",
            "snapshot_version",
            name="uq_incident_snapshots_incident_version",
        ),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("author_id", sa.String(length=255), nullable=False),
        sa.Column(
            "algorithm_config_version",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["wildfire_incidents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "scenario_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "incident_snapshot_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("graph_version", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_snapshot_id"],
            ["incident_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id",
            "version",
            name="uq_scenario_versions_scenario_version",
        ),
    )

    op.create_table(
        "scenario_road_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("edge_id", sa.String(length=255), nullable=False),
        sa.Column("capacity_multiplier", sa.Float(), nullable=True),
        sa.Column(
            "reopens_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_version_id",
            "edge_id",
            name="uq_scenario_road_closures_version_edge",
        ),
    )

    op.create_table(
        "scenario_weather_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("wind_speed_mps", sa.Float(), nullable=False),
        sa.Column("wind_direction_degrees", sa.Float(), nullable=False),
        sa.Column("forecast_horizon_hours", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "scenario_resource_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=255), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource_units.resource_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_version_id",
            "resource_id",
            name="uq_scenario_resource_overrides_version_resource",
        ),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_type", sa.String(length=100), nullable=True),
        sa.Column("response_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "key",
            name="uq_idempotency_keys_scope_key",
        ),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scenario_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("input_version", sa.String(length=255), nullable=False),
        sa.Column(
            "source_versions",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("graph_version", sa.String(length=255), nullable=False),
        sa.Column("risk_version", sa.String(length=255), nullable=False),
        sa.Column("algorithm_version", sa.String(length=255), nullable=False),
        sa.Column("solver_status", sa.String(length=40), nullable=False),
        sa.Column("runtime_milliseconds", sa.Integer(), nullable=False),
        sa.Column("request_inputs", postgresql.JSONB(), nullable=False),
        sa.Column("objective_components", postgresql.JSONB(), nullable=False),
        sa.Column(
            "uncovered_destination_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("explanation", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_key_id"],
            ["idempotency_keys.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"],
            ["scenario_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key_id",
            name="uq_recommendations_idempotency_key",
        ),
    )

    op.create_table(
        "recommendation_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recommendation_id",
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
            server_default=sa.text("'proposed'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["exposed_assets.asset_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resource_units.resource_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id",
            "resource_id",
            name="uq_recommendation_assignments_recommendation_resource",
        ),
    )

    op.create_table(
        "decision_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column(
            "edited_assignments",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_key_id"],
            ["idempotency_keys.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key_id",
            name="uq_decision_actions_idempotency_key",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "decision_action_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column(
            "inputs",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decision_action_id"],
            ["decision_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("decision_actions")
    op.drop_table("recommendation_assignments")
    op.drop_table("recommendations")
    op.drop_table("idempotency_keys")
    op.drop_table("scenario_resource_overrides")
    op.drop_table("scenario_weather_overrides")
    op.drop_table("scenario_road_closures")
    op.drop_table("scenario_versions")
    op.drop_table("scenarios")
    op.drop_table("incident_snapshots")
    op.drop_table("source_status")
    op.drop_index("ix_resource_units_geometry", table_name="resource_units")
    op.drop_table("resource_units")
    op.drop_index("ix_exposed_assets_geometry", table_name="exposed_assets")
    op.drop_table("exposed_assets")
    op.drop_table("incident_detections")
    op.drop_index(
        "ix_wildfire_incidents_geometry",
        table_name="wildfire_incidents",
    )
    op.drop_table("wildfire_incidents")
    op.drop_table("quarantined_observations")
    op.drop_index(
        "ix_source_observations_geometry",
        table_name="source_observations",
    )
    op.drop_table("source_observations")
