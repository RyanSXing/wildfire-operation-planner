"""PostGIS exposure queries and immutable incident snapshot refresh."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import json
from math import isfinite
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import String, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.decision.risk import (
    RiskConfig,
    normalize_risk_inputs,
    score_risk,
    serialize_risk_breakdown,
    serialize_risk_config,
)
from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.exposure import (
    ExposedAssetExposure,
    ExposureConfig,
    validate_buffer_meters,
)
from wildfireops.persistence.decision_models import IncidentSnapshotModel
from wildfireops.persistence.incidents import acquire_incident_refresh_lock
from wildfireops.persistence.observed_models import (
    ExposedAssetModel,
    IncidentDetectionModel,
    ResourceUnitModel,
    SourceObservationModel,
    WildfireIncidentModel,
)


_WGS84_GEOGRAPHY = Geography(geometry_type="GEOMETRY", srid=4326)


class ExposureRepository:
    async def find_for_incident(
        self,
        session: AsyncSession,
        incident_id: UUID,
        buffer_meters: float,
    ) -> tuple[ExposedAssetExposure, ...]:
        bounded_buffer = validate_buffer_meters(buffer_meters)
        if not isinstance(incident_id, UUID):
            raise ValueError("incident_id must be a UUID")

        anchor = func.ST_PointOnSurface(WildfireIncidentModel.geometry)
        closest_asset_point = func.ST_ClosestPoint(
            ExposedAssetModel.geometry,
            anchor,
        )
        asset_geography = cast(ExposedAssetModel.geometry, _WGS84_GEOGRAPHY)
        incident_geography = cast(WildfireIncidentModel.geometry, _WGS84_GEOGRAPHY)
        anchor_geography = cast(anchor, _WGS84_GEOGRAPHY)
        closest_geography = cast(closest_asset_point, _WGS84_GEOGRAPHY)
        distance = func.ST_Distance(asset_geography, incident_geography)
        anchor_distance = func.ST_Distance(anchor_geography, closest_geography)
        bearing = case(
            (anchor_distance == 0, None),
            else_=func.degrees(func.ST_Azimuth(anchor_geography, closest_geography)),
        )
        statement = (
            select(
                ExposedAssetModel.asset_id,
                ExposedAssetModel.asset_kind,
                ExposedAssetModel.name,
                ExposedAssetModel.population,
                ExposedAssetModel.capacity,
                ExposedAssetModel.source_name,
                ExposedAssetModel.source_version,
                func.ST_AsGeoJSON(ExposedAssetModel.geometry, 15).label(
                    "geometry_geojson"
                ),
                ExposedAssetModel.raw_metadata,
                distance.label("distance_meters"),
                bearing.label("bearing_degrees"),
            )
            .select_from(ExposedAssetModel)
            .join(WildfireIncidentModel, WildfireIncidentModel.id == incident_id)
            .where(
                func.ST_DWithin(
                    asset_geography,
                    incident_geography,
                    bounded_buffer,
                )
            )
            .order_by(distance, ExposedAssetModel.asset_id)
        )
        rows = (await session.execute(statement)).all()
        return tuple(
            ExposedAssetExposure(
                asset_id=row.asset_id,
                asset_kind=row.asset_kind,
                name=row.name,
                population=row.population,
                capacity=row.capacity,
                source_name=row.source_name,
                source_version=row.source_version,
                geometry_geojson=json.loads(row.geometry_geojson),
                raw_metadata=row.raw_metadata,
                distance_meters=row.distance_meters,
                bearing_degrees=row.bearing_degrees,
            )
            for row in rows
        )


async def refresh_exposure_and_risk(
    session: AsyncSession,
    *,
    reference_at: datetime,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
    clustering_algorithm_version: str,
) -> tuple[UUID, ...]:
    """Refresh active incident risk and immutable snapshots in one transaction.

    The caller owns commit and rollback. Re-acquiring the ingestion transaction
    advisory lock makes the public function safe for direct concurrent callers.
    """
    _require_utc(reference_at, "reference_at")
    if (
        not isinstance(clustering_algorithm_version, str)
        or not clustering_algorithm_version.strip()
    ):
        raise ValueError("clustering_algorithm_version must be nonblank")
    await acquire_incident_refresh_lock(session)

    weather = await _load_weather_observations(session, reference_at)
    weather_by_identity = {item.identity: item for item in weather}
    resource_state = await _load_resource_state(session)
    repository = ExposureRepository()
    snapshot_ids: list[UUID] = []

    anchor = func.ST_PointOnSurface(WildfireIncidentModel.geometry)
    incident_rows = (
        await session.execute(
            select(
                WildfireIncidentModel,
                func.ST_AsGeoJSON(WildfireIncidentModel.geometry, 15).label(
                    "geometry_geojson"
                ),
                func.ST_X(anchor).label("anchor_longitude"),
                func.ST_Y(anchor).label("anchor_latitude"),
            )
            .where(WildfireIncidentModel.status == "active")
            .order_by(cast(WildfireIncidentModel.id, String))
        )
    ).all()
    for row in incident_rows:
        incident = row.WildfireIncidentModel
        exposures = await repository.find_for_incident(
            session,
            incident.id,
            exposure_config.buffer_meters,
        )
        detections = await _load_incident_detections(session, incident.id)
        normalized = normalize_risk_inputs(
            exposures=exposures,
            detections=detections,
            weather_observations=weather,
            incident_longitude=row.anchor_longitude,
            incident_latitude=row.anchor_latitude,
            reference_at=reference_at,
            exposure_buffer_meters=exposure_config.buffer_meters,
            config=risk_config,
        )
        breakdown = score_risk(normalized.factors, risk_config)
        incident.risk_score = breakdown.score
        selected_weather = (
            None
            if normalized.selected_weather_identity is None
            else weather_by_identity[normalized.selected_weather_identity]
        )
        source_versions = _source_versions(
            detections=detections,
            selected_weather=selected_weather,
            exposures=exposures,
        )
        asset_state = _asset_state(exposures)
        risk_state = serialize_risk_breakdown(
            breakdown,
            normalized.raw_evidence,
        )
        risk_state["config"] = serialize_risk_config(risk_config)
        incident_state: dict[str, object] = {
            "status": incident.status,
            "geometry_geojson": _canonical_source_json(
                json.loads(row.geometry_geojson)
            ),
            "first_observed_at": _utc_iso(incident.first_observed_at),
            "last_observed_at": _utc_iso(incident.last_observed_at),
            "reference_at": _utc_iso(reference_at),
            "detection_identities": sorted(item.identity for item in detections),
            "clustering_algorithm_version": clustering_algorithm_version.strip(),
            "exposure": {
                "buffer_meters": _calculated_float(exposure_config.buffer_meters)
            },
            "risk": risk_state,
        }
        snapshot = await _reuse_or_create_snapshot(
            session,
            incident_id=incident.id,
            reference_at=reference_at,
            source_versions=source_versions,
            incident_state=incident_state,
            asset_state=asset_state,
            resource_state=resource_state,
        )
        snapshot_ids.append(snapshot.id)
    return tuple(snapshot_ids)


async def _load_incident_detections(
    session: AsyncSession,
    incident_id: UUID,
) -> tuple[NormalizedObservation, ...]:
    rows = (
        await session.execute(
            select(
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
                SourceObservationModel.observed_at,
                func.ST_X(SourceObservationModel.geometry).label("longitude"),
                func.ST_Y(SourceObservationModel.geometry).label("latitude"),
                SourceObservationModel.confidence,
                SourceObservationModel.intensity,
                SourceObservationModel.raw_payload,
            )
            .join(
                IncidentDetectionModel,
                IncidentDetectionModel.observation_id == SourceObservationModel.id,
            )
            .where(
                IncidentDetectionModel.incident_id == incident_id,
                SourceObservationModel.observation_kind == "fire",
            )
            .order_by(
                SourceObservationModel.observed_at,
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
            )
        )
    ).all()
    detections: list[NormalizedObservation] = []
    for row in rows:
        if row.confidence is None:
            raise ValueError("stored fire detection confidence is required")
        detections.append(
            NormalizedObservation(
                source_name=row.source_name,
                source_record_id=row.source_record_id,
                observed_at=row.observed_at,
                longitude=row.longitude,
                latitude=row.latitude,
                confidence=row.confidence,
                intensity=row.intensity,
                raw_payload=row.raw_payload,
            )
        )
    return tuple(detections)


async def _load_weather_observations(
    session: AsyncSession,
    reference_at: datetime,
) -> tuple[WeatherObservation, ...]:
    rows = (
        await session.execute(
            select(
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
                SourceObservationModel.observed_at,
                func.ST_X(SourceObservationModel.geometry).label("longitude"),
                func.ST_Y(SourceObservationModel.geometry).label("latitude"),
                SourceObservationModel.wind_speed_mps,
                SourceObservationModel.wind_direction_degrees,
                SourceObservationModel.temperature_celsius,
                SourceObservationModel.raw_payload,
            )
            .where(
                SourceObservationModel.observation_kind == "weather",
                SourceObservationModel.observed_at <= reference_at,
            )
            .order_by(
                SourceObservationModel.observed_at.desc(),
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
            )
        )
    ).all()
    observations: list[WeatherObservation] = []
    for row in rows:
        if row.wind_speed_mps is None or row.wind_direction_degrees is None:
            raise ValueError("stored weather wind measurements are required")
        observations.append(
            WeatherObservation(
                source_name=row.source_name,
                source_record_id=row.source_record_id,
                observed_at=row.observed_at,
                longitude=row.longitude,
                latitude=row.latitude,
                wind_speed_mps=row.wind_speed_mps,
                wind_direction_degrees=row.wind_direction_degrees,
                temperature_celsius=row.temperature_celsius,
                raw_payload=row.raw_payload,
            )
        )
    return tuple(observations)


async def _load_resource_state(session: AsyncSession) -> list[object]:
    rows = (
        await session.execute(
            select(
                ResourceUnitModel.resource_id,
                ResourceUnitModel.resource_type,
                ResourceUnitModel.capabilities,
                ResourceUnitModel.capacity,
                ResourceUnitModel.available,
                ResourceUnitModel.status,
                func.ST_AsGeoJSON(ResourceUnitModel.geometry, 15).label(
                    "geometry_geojson"
                ),
                ResourceUnitModel.raw_metadata,
            ).order_by(ResourceUnitModel.resource_id)
        )
    ).all()
    state: list[object] = []
    for row in rows:
        capabilities = row.capabilities
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ):
            raise ValueError("stored resource capabilities must be nonblank strings")
        state.append(
            {
                "resource_id": row.resource_id,
                "resource_type": row.resource_type,
                "capabilities": sorted(item.strip() for item in capabilities),
                "capacity": row.capacity,
                "available": row.available,
                "status": row.status,
                "geometry_geojson": _canonical_source_json(
                    json.loads(row.geometry_geojson)
                ),
                "raw_metadata": _canonical_source_json(row.raw_metadata),
            }
        )
    return state


def _source_versions(
    *,
    detections: Sequence[NormalizedObservation],
    selected_weather: WeatherObservation | None,
    exposures: Sequence[ExposedAssetExposure],
) -> dict[str, object]:
    observations: tuple[NormalizedObservation | WeatherObservation, ...] = (
        *detections,
        *((selected_weather,) if selected_weather is not None else ()),
    )
    grouped: dict[
        tuple[str, None], list[NormalizedObservation | WeatherObservation]
    ] = {}
    for observation in observations:
        grouped.setdefault((observation.source_name, None), []).append(observation)
    observation_inputs = [
        {
            "source_name": source_name,
            "source_version": source_version,
            "record_ids": sorted(item.source_record_id for item in items),
            "latest_observed_at": _utc_iso(max(item.observed_at for item in items)),
        }
        for (source_name, source_version), items in sorted(
            grouped.items(),
            key=lambda item: item[0][0],
        )
    ]
    asset_pairs = {
        (exposure.source_name, exposure.source_version) for exposure in exposures
    }
    asset_inputs = [
        {"source_name": source_name, "source_version": source_version}
        for source_name, source_version in sorted(
            asset_pairs,
            key=lambda item: (item[0] or "", item[1] or ""),
        )
    ]
    return {
        "observation_inputs": observation_inputs,
        "asset_inputs": asset_inputs,
    }


def _asset_state(exposures: Sequence[ExposedAssetExposure]) -> list[object]:
    return [
        {
            "asset_id": exposure.asset_id,
            "asset_kind": exposure.asset_kind,
            "name": exposure.name,
            "population": exposure.population,
            "capacity": exposure.capacity,
            "source_name": exposure.source_name,
            "source_version": exposure.source_version,
            "geometry_geojson": _canonical_source_json(exposure.geometry_geojson),
            "raw_metadata": _canonical_source_json(exposure.raw_metadata),
            "distance_meters": _calculated_float(exposure.distance_meters),
            "bearing_degrees": (
                None
                if exposure.bearing_degrees is None
                else _calculated_float(exposure.bearing_degrees)
            ),
        }
        for exposure in sorted(exposures, key=lambda item: item.asset_id)
    ]


async def _reuse_or_create_snapshot(
    session: AsyncSession,
    *,
    incident_id: UUID,
    reference_at: datetime,
    source_versions: dict[str, object],
    incident_state: dict[str, object],
    asset_state: list[object],
    resource_state: list[object],
) -> IncidentSnapshotModel:
    latest = await session.scalar(
        select(IncidentSnapshotModel)
        .where(IncidentSnapshotModel.incident_id == incident_id)
        .order_by(IncidentSnapshotModel.snapshot_version.desc())
        .limit(1)
    )
    if latest is not None:
        previous_name = latest.incident_state.get("name")
        if (
            "name" not in incident_state
            and isinstance(previous_name, str)
            and previous_name.strip()
        ):
            incident_state = {**incident_state, "name": previous_name.strip()}
        is_identical = await session.scalar(
            select(
                and_(
                    IncidentSnapshotModel.source_versions == source_versions,
                    IncidentSnapshotModel.incident_state == incident_state,
                    IncidentSnapshotModel.asset_state == asset_state,
                    IncidentSnapshotModel.resource_state == resource_state,
                )
            ).where(IncidentSnapshotModel.id == latest.id)
        )
        if is_identical:
            return latest
    snapshot = IncidentSnapshotModel(
        incident_id=incident_id,
        snapshot_version=1 if latest is None else latest.snapshot_version + 1,
        source_versions=source_versions,
        incident_state=incident_state,
        asset_state=asset_state,
        resource_state=resource_state,
        captured_at=reference_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


def _canonical_source_json(value: object) -> object:
    if isinstance(value, Mapping):
        canonical: dict[str, object] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError("snapshot JSON keys must be strings")
            canonical[key] = _canonical_source_json(value[key])
        return canonical
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_source_json(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("snapshot JSON values must be finite")
        return value
    if value is None or isinstance(value, bool | int | str):
        return value
    raise ValueError(f"unsupported snapshot JSON value: {type(value).__name__}")


def _calculated_float(value: float) -> float:
    if not isfinite(value):
        raise ValueError("calculated snapshot values must be finite")
    return round(value, 6)


def _require_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return value


def _utc_iso(value: datetime) -> str:
    return _require_utc(value, "snapshot timestamp").isoformat().replace("+00:00", "Z")
