from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from wildfireops.domain.observations import (
    FrozenJsonObject,
    FrozenJsonValue,
    NormalizedObservation,
    SourceObservation,
    WeatherObservation,
)
from wildfireops.persistence.base import Base


def _materialize_json_value(value: FrozenJsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _materialize_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_materialize_json_value(item) for item in value]
    return value


def _materialize_json_object(payload: FrozenJsonObject) -> dict[str, object]:
    return {key: _materialize_json_value(value) for key, value in payload.items()}


class SourceObservationModel(Base):
    __tablename__ = "source_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "source_record_id",
            name="uq_source_observations_source_identity",
        ),
        CheckConstraint(
            "observation_kind IN ('fire', 'weather')",
            name="ck_source_observations_kind",
        ),
        Index(
            "ix_source_observations_geometry",
            "geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    observation_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction_degrees: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    temperature_celsius: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    @staticmethod
    def from_domain(record: SourceObservation) -> dict[str, object]:
        values: dict[str, object] = {
            "source_name": record.source_name,
            "source_record_id": record.source_record_id,
            "observed_at": record.observed_at,
            "geometry": WKTElement(
                f"POINT({record.longitude} {record.latitude})",
                srid=4326,
            ),
            "raw_payload": _materialize_json_object(record.raw_payload),
        }

        if isinstance(record, NormalizedObservation):
            values.update(
                observation_kind="fire",
                confidence=record.confidence,
                intensity=record.intensity,
                wind_speed_mps=None,
                wind_direction_degrees=None,
                temperature_celsius=None,
            )
        elif isinstance(record, WeatherObservation):
            values.update(
                observation_kind="weather",
                confidence=None,
                intensity=None,
                wind_speed_mps=record.wind_speed_mps,
                wind_direction_degrees=record.wind_direction_degrees,
                temperature_celsius=record.temperature_celsius,
            )
        else:
            raise TypeError(f"unsupported observation type: {type(record).__name__}")

        return values


class QuarantinedObservationModel(Base):
    __tablename__ = "quarantined_observations"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    validation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WildfireIncidentModel(Base):
    __tablename__ = "wildfire_incidents"
    __table_args__ = (
        Index(
            "ix_wildfire_incidents_geometry",
            "geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    severity_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=False,
    )
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IncidentDetectionModel(Base):
    __tablename__ = "incident_detections"
    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "observation_id",
            name="uq_incident_detections_membership",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    incident_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("wildfire_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    observation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ExposedAssetModel(Base):
    __tablename__ = "exposed_assets"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_exposed_assets_asset_id"),
        Index(
            "ix_exposed_assets_geometry",
            "geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=False,
    )
    raw_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ResourceUnitModel(Base):
    __tablename__ = "resource_units"
    __table_args__ = (
        UniqueConstraint("resource_id", name="uq_resource_units_resource_id"),
        Index(
            "ix_resource_units_geometry",
            "geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    capabilities: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="available",
        server_default=text("'available'"),
    )
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    raw_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SourceStatusModel(Base):
    __tablename__ = "source_status"
    __table_args__ = (
        UniqueConstraint("source_name", name="uq_source_status_source_name"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    last_attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    deduplicated_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    quarantined_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
