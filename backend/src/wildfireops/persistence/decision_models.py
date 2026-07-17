from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from wildfireops.persistence.base import Base


class IncidentSnapshotModel(Base):
    __tablename__ = "incident_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "snapshot_version",
            name="uq_incident_snapshots_incident_version",
        ),
        UniqueConstraint(
            "id",
            "incident_id",
            name="uq_incident_snapshots_id_incident",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    incident_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("wildfire_incidents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_versions: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    incident_state: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    asset_state: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    resource_state: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ScenarioModel(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "incident_id",
            name="uq_scenarios_id_incident",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    incident_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("wildfire_incidents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm_config_version: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ScenarioVersionModel(Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id",
            "version",
            name="uq_scenario_versions_scenario_version",
        ),
        ForeignKeyConstraint(
            ["scenario_id", "incident_id"],
            ["scenarios.id", "scenarios.incident_id"],
            name="fk_scenario_versions_scenario_incident",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["incident_snapshot_id", "incident_id"],
            ["incident_snapshots.id", "incident_snapshots.incident_id"],
            name="fk_scenario_versions_snapshot_incident",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    incident_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    incident_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    graph_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ScenarioRoadClosureModel(Base):
    __tablename__ = "scenario_road_closures"
    __table_args__ = (
        UniqueConstraint(
            "scenario_version_id",
            "edge_id",
            name="uq_scenario_road_closures_version_edge",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scenario_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_multiplier: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    reopens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ScenarioWeatherOverrideModel(Base):
    __tablename__ = "scenario_weather_overrides"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scenario_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    wind_speed_mps: Mapped[float] = mapped_column(Float, nullable=False)
    wind_direction_degrees: Mapped[float] = mapped_column(Float, nullable=False)
    forecast_horizon_hours: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


class ScenarioResourceOverrideModel(Base):
    __tablename__ = "scenario_resource_overrides"
    __table_args__ = (
        UniqueConstraint(
            "scenario_version_id",
            "resource_id",
            name="uq_scenario_resource_overrides_version_resource",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scenario_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "key",
            name="uq_idempotency_keys_scope_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RecommendationModel(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key_id",
            name="uq_recommendations_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    scenario_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenario_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
        nullable=True,
    )
    input_version: Mapped[str] = mapped_column(String(255), nullable=False)
    source_versions: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    graph_version: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_version: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(255), nullable=False)
    solver_status: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    objective_components: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    uncovered_destination_ids: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    explanation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RecommendationAssignmentModel(Base):
    __tablename__ = "recommendation_assignments"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "resource_id",
            name="uq_recommendation_assignments_recommendation_resource",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("resource_units.resource_id", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("exposed_assets.asset_id", ondelete="RESTRICT"),
        nullable=False,
    )
    route: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    travel_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="proposed",
        server_default=text("'proposed'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DecisionActionModel(Base):
    __tablename__ = "decision_actions"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key_id",
            name="uq_decision_actions_idempotency_key",
        ),
        UniqueConstraint(
            "recommendation_id",
            name="uq_decision_actions_recommendation",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("idempotency_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    edited_assignments: Mapped[list[object]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DecisionAssignmentModel(Base):
    __tablename__ = "decision_assignments"
    __table_args__ = (
        UniqueConstraint(
            "decision_action_id",
            "resource_id",
            name="uq_decision_assignments_decision_resource",
        ),
        Index(
            "uq_decision_assignments_active_resource",
            "resource_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    decision_action_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("resource_units.resource_id", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("exposed_assets.asset_id", ondelete="RESTRICT"),
        nullable=False,
    )
    route: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    travel_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint(
            "decision_action_id",
            name="uq_audit_events_decision_action",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    decision_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_actions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    before_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    after_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    inputs: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
