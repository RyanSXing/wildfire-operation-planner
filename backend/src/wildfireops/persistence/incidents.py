from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import hypot, isfinite
from typing import cast
from uuid import UUID

from geoalchemy2.elements import WKBElement, WKTElement
from pyproj import Transformer
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import NormalizedObservation
from wildfireops.geospatial.clustering import DetectionCluster
from wildfireops.persistence.observed_models import (
    IncidentDetectionModel,
    SourceObservationModel,
    WildfireIncidentModel,
)


_TO_EPSG_3310 = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True)
DEFAULT_INCIDENT_MATCH_RADIUS_METERS = 5_000.0
_INCIDENT_REFRESH_LOCK_ID = int.from_bytes(b"WFIREOPS", byteorder="big")


@dataclass(frozen=True, slots=True)
class _ExistingIncident:
    model: WildfireIncidentModel
    longitude: float
    latitude: float
    member_identities: frozenset[str]


async def load_current_fire_detections(
    session: AsyncSession,
    *,
    reference_at: datetime,
    temporal_window_seconds: float,
) -> tuple[NormalizedObservation, ...]:
    window_start = _window_start(reference_at, temporal_window_seconds)
    statement = (
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
        .where(
            SourceObservationModel.observation_kind == "fire",
            SourceObservationModel.observed_at >= window_start,
            SourceObservationModel.observed_at <= reference_at,
        )
        .order_by(
            SourceObservationModel.observed_at,
            SourceObservationModel.source_name,
            SourceObservationModel.source_record_id,
        )
    )
    rows = (await session.execute(statement)).all()
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


async def acquire_incident_refresh_lock(session: AsyncSession) -> None:
    """Serialize the read/cluster/refresh critical section for one transaction."""
    await session.execute(select(func.pg_advisory_xact_lock(_INCIDENT_REFRESH_LOCK_ID)))


def _window_start(
    reference_at: datetime,
    temporal_window_seconds: float,
) -> datetime:
    if not isinstance(reference_at, datetime) or reference_at.utcoffset() != timedelta(
        0
    ):
        raise ValueError("reference_at must be UTC")
    if isinstance(temporal_window_seconds, bool) or not isinstance(
        temporal_window_seconds, (int, float)
    ):
        raise ValueError("temporal_window_seconds must be a finite positive number")
    try:
        seconds = float(temporal_window_seconds)
    except (OverflowError, ValueError):
        raise ValueError(
            "temporal_window_seconds must be a finite positive number"
        ) from None
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("temporal_window_seconds must be a finite positive number")
    try:
        return reference_at - timedelta(seconds=seconds)
    except OverflowError:
        raise ValueError("detection time window must be representable") from None


async def refresh_incidents(
    session: AsyncSession,
    clusters: Sequence[DetectionCluster],
    spatial_radius_meters: float = DEFAULT_INCIDENT_MATCH_RADIUS_METERS,
) -> None:
    # Direct callers are serialized too. Ingestion acquires the same re-entrant
    # transaction lock before it reads detections so waiting runs recompute.
    await acquire_incident_refresh_lock(session)
    observations = await _observation_members(session)
    ordered_clusters = tuple(sorted(clusters, key=lambda item: item.member_identities))
    existing = await _existing_incidents(session)
    assignments = _match_existing_incidents(
        ordered_clusters,
        existing,
        spatial_radius_meters,
    )

    await session.execute(delete(IncidentDetectionModel))
    for existing_incident in existing:
        existing_incident.model.status = "inactive"

    for cluster_index, cluster in enumerate(ordered_clusters):
        members = [observations[identity] for identity in cluster.member_identities]
        first_observed_at = min(member[1] for member in members)
        last_observed_at = max(member[1] for member in members)
        geometry = cast(
            WKBElement,
            WKTElement(
                f"POINT({cluster.centroid_longitude} {cluster.centroid_latitude})",
                srid=4326,
            ),
        )
        matched = assignments.get(cluster_index)
        if matched is None:
            incident_model = WildfireIncidentModel(
                geometry=geometry,
                first_observed_at=first_observed_at,
                last_observed_at=last_observed_at,
            )
            session.add(incident_model)
            await session.flush()
        else:
            incident_model = matched.model
            incident_model.status = "active"
            incident_model.geometry = geometry
            incident_model.first_observed_at = min(
                incident_model.first_observed_at,
                first_observed_at,
            )
            incident_model.last_observed_at = max(
                incident_model.last_observed_at,
                last_observed_at,
            )
        session.add_all(
            [
                IncidentDetectionModel(
                    incident_id=incident_model.id,
                    observation_id=observations[identity][0],
                )
                for identity in cluster.member_identities
            ]
        )


async def _observation_members(
    session: AsyncSession,
) -> dict[str, tuple[UUID, datetime]]:
    rows = (
        await session.execute(
            select(
                SourceObservationModel.id,
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
                SourceObservationModel.observed_at,
            ).where(SourceObservationModel.observation_kind == "fire")
        )
    ).all()
    return {
        f"{row.source_name}:{row.source_record_id}": (row.id, row.observed_at)
        for row in rows
    }


async def _existing_incidents(
    session: AsyncSession,
) -> tuple[_ExistingIncident, ...]:
    membership_rows = (
        await session.execute(
            select(
                IncidentDetectionModel.incident_id,
                SourceObservationModel.source_name,
                SourceObservationModel.source_record_id,
            ).join(
                SourceObservationModel,
                SourceObservationModel.id == IncidentDetectionModel.observation_id,
            )
        )
    ).all()
    members: dict[UUID, set[str]] = {}
    for row in membership_rows:
        members.setdefault(row.incident_id, set()).add(
            f"{row.source_name}:{row.source_record_id}"
        )

    centroid = func.ST_Centroid(WildfireIncidentModel.geometry)
    incident_rows = (
        await session.execute(
            select(
                WildfireIncidentModel,
                func.ST_X(centroid).label("longitude"),
                func.ST_Y(centroid).label("latitude"),
            )
        )
    ).all()
    return tuple(
        sorted(
            (
                _ExistingIncident(
                    model=row.WildfireIncidentModel,
                    longitude=row.longitude,
                    latitude=row.latitude,
                    member_identities=frozenset(
                        members.get(row.WildfireIncidentModel.id, set())
                    ),
                )
                for row in incident_rows
            ),
            key=lambda incident: str(incident.model.id),
        )
    )


def _match_existing_incidents(
    clusters: Sequence[DetectionCluster],
    existing: Sequence[_ExistingIncident],
    spatial_radius_meters: float,
) -> dict[int, _ExistingIncident]:
    candidate_pairs: list[
        tuple[int, int, float, str, tuple[str, ...], int, _ExistingIncident]
    ] = []
    for cluster_index, cluster in enumerate(clusters):
        cluster_easting, cluster_northing = _TO_EPSG_3310.transform(
            cluster.centroid_longitude,
            cluster.centroid_latitude,
        )
        cluster_members = frozenset(cluster.member_identities)
        for incident in existing:
            incident_easting, incident_northing = _TO_EPSG_3310.transform(
                incident.longitude,
                incident.latitude,
            )
            distance = hypot(
                cluster_easting - incident_easting,
                cluster_northing - incident_northing,
            )
            overlap = len(cluster_members & incident.member_identities)
            if overlap == 0 and distance > spatial_radius_meters:
                continue
            candidate_pairs.append(
                (
                    0 if overlap else 1,
                    -overlap,
                    distance,
                    str(incident.model.id),
                    cluster.member_identities,
                    cluster_index,
                    incident,
                )
            )

    assignments: dict[int, _ExistingIncident] = {}
    assigned_incidents: set[UUID] = set()
    for *_, cluster_index, incident in sorted(candidate_pairs):
        if (
            cluster_index not in assignments
            and incident.model.id not in assigned_incidents
        ):
            assignments[cluster_index] = incident
            assigned_incidents.add(incident.model.id)
    return assignments
