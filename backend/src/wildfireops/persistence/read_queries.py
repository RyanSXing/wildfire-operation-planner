from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from wildfireops.application.read_models import (
    DetailedRiskReadModel,
    DetectionReadModel,
    ExposedAssetReadModel,
    Freshness,
    IncidentDetailReadModel,
    IncidentQueryService,
    IncidentSummaryReadModel,
    ReadModelNotFound,
    RiskContributionReadModel,
    RiskReadModel,
    SimulatedResourceReadModel,
    SourceQueryService,
    SourceStatusReadModel,
    TimelineFrameReadModel,
)
from wildfireops.config import Settings
from wildfireops.domain.observations import (
    FrozenJsonObject,
    freeze_json_object,
    freeze_json_value,
)
from wildfireops.persistence.decision_models import IncidentSnapshotModel
from wildfireops.persistence.observed_models import (
    SourceObservationModel,
    SourceStatusModel,
    WildfireIncidentModel,
)


type UtcClock = Callable[[], datetime]
type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlAlchemyReadServiceProvider:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: Settings,
        clock: UtcClock,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock

    def incidents(self) -> AbstractAsyncContextManager[IncidentQueryService]:
        return self._incidents()

    def sources(self) -> AbstractAsyncContextManager[SourceQueryService]:
        return self._sources()

    @asynccontextmanager
    async def _incidents(self) -> AsyncIterator[IncidentQueryService]:
        async with self._session_factory() as session:
            try:
                yield SqlAlchemyIncidentQueryService(session, self._settings)
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def _sources(self) -> AsyncIterator[SourceQueryService]:
        async with self._session_factory() as session:
            try:
                yield SqlAlchemySourceQueryService(
                    session,
                    self._settings,
                    self._clock,
                )
            except Exception:
                await session.rollback()
                raise


class SqlAlchemyIncidentQueryService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def list_incidents(self) -> tuple[IncidentSummaryReadModel, ...]:
        latest_versions = _latest_snapshot_versions()
        rows = (
            await self._session.execute(
                select(IncidentSnapshotModel)
                .join(
                    latest_versions,
                    (latest_versions.c.incident_id == IncidentSnapshotModel.incident_id)
                    & (
                        latest_versions.c.snapshot_version
                        == IncidentSnapshotModel.snapshot_version
                    ),
                )
                .join(
                    WildfireIncidentModel,
                    WildfireIncidentModel.id == IncidentSnapshotModel.incident_id,
                )
                .where(WildfireIncidentModel.status == "active")
                .order_by(
                    WildfireIncidentModel.risk_score.desc().nullslast(),
                    WildfireIncidentModel.id,
                )
            )
        ).scalars()
        return tuple(self._summary(snapshot) for snapshot in rows)

    async def get_incident(
        self,
        incident_id: str | UUID,
    ) -> IncidentDetailReadModel:
        requested_id, parsed_id = _parse_incident_id(incident_id)
        snapshot = await self._session.scalar(
            select(IncidentSnapshotModel)
            .where(IncidentSnapshotModel.incident_id == parsed_id)
            .order_by(IncidentSnapshotModel.snapshot_version.desc())
            .limit(1)
        )
        if snapshot is None:
            raise _incident_not_found(requested_id)
        state = _mapping(snapshot.incident_state, "incident state")
        last_observed_at = _timestamp(state.get("last_observed_at"), "last observed")
        return IncidentDetailReadModel(
            id=str(snapshot.incident_id),
            name=_incident_name(state, snapshot.incident_id),
            status=_string(state.get("status"), "incident status"),
            snapshot_id=str(snapshot.id),
            snapshot_version=snapshot.snapshot_version,
            geometry=_json_object(state.get("geometry_geojson"), "incident geometry"),
            first_observed_at=_timestamp(
                state.get("first_observed_at"), "first observed"
            ),
            last_observed_at=last_observed_at,
            freshness=_snapshot_freshness(
                state,
                last_observed_at,
                self._settings.risk_fire_freshness_seconds,
            ),
            risk=_detailed_risk(state.get("risk")),
            detections=await self._detections(state),
            exposed_assets=_assets(snapshot.asset_state),
            simulated_resources=_simulated_resources(snapshot.resource_state),
            source_versions=_json_object(
                snapshot.source_versions, "snapshot source versions"
            ),
        )

    async def get_timeline(
        self,
        incident_id: str | UUID,
    ) -> tuple[TimelineFrameReadModel, ...]:
        requested_id, parsed_id = _parse_incident_id(incident_id)
        snapshots = (
            await self._session.scalars(
                select(IncidentSnapshotModel)
                .where(IncidentSnapshotModel.incident_id == parsed_id)
                .order_by(
                    IncidentSnapshotModel.captured_at,
                    IncidentSnapshotModel.snapshot_version,
                    IncidentSnapshotModel.id,
                )
            )
        ).all()
        if not snapshots:
            raise _incident_not_found(requested_id)
        frames: list[TimelineFrameReadModel] = []
        for snapshot in snapshots:
            state = _mapping(snapshot.incident_state, "incident state")
            last_observed_at = _timestamp(
                state.get("last_observed_at"), "last observed"
            )
            assets = _sequence(snapshot.asset_state, "snapshot assets")
            frames.append(
                TimelineFrameReadModel(
                    snapshot_id=str(snapshot.id),
                    snapshot_version=snapshot.snapshot_version,
                    captured_at=_utc(snapshot.captured_at, "snapshot capture time"),
                    reference_at=_timestamp(
                        state.get("reference_at"), "snapshot reference"
                    ),
                    last_observed_at=last_observed_at,
                    geometry=_json_object(
                        state.get("geometry_geojson"), "incident geometry"
                    ),
                    risk=_risk(state.get("risk")),
                    detections=await self._detections(state),
                    exposed_asset_count=len(assets),
                    freshness=_snapshot_freshness(
                        state,
                        last_observed_at,
                        self._settings.risk_fire_freshness_seconds,
                    ),
                )
            )
        return tuple(frames)

    def _summary(
        self,
        snapshot: IncidentSnapshotModel,
    ) -> IncidentSummaryReadModel:
        state = _mapping(snapshot.incident_state, "incident state")
        assets = _sequence(snapshot.asset_state, "snapshot assets")
        last_observed_at = _timestamp(state.get("last_observed_at"), "last observed")
        return IncidentSummaryReadModel(
            id=str(snapshot.incident_id),
            name=_incident_name(state, snapshot.incident_id),
            risk=_risk(state.get("risk")),
            exposed_asset_count=len(assets),
            last_observed_at=last_observed_at,
            freshness=_snapshot_freshness(
                state,
                last_observed_at,
                self._settings.risk_fire_freshness_seconds,
            ),
        )

    async def _detections(
        self,
        state: Mapping[str, object],
    ) -> tuple[DetectionReadModel, ...]:
        raw_identities = _sequence(
            state.get("detection_identities"), "detection identities"
        )
        identities = tuple(
            _identity(item, "detection identity") for item in raw_identities
        )
        if not identities:
            return ()
        rows = (
            await self._session.execute(
                select(
                    SourceObservationModel.source_name,
                    SourceObservationModel.source_record_id,
                    SourceObservationModel.observed_at,
                    func.ST_AsGeoJSON(SourceObservationModel.geometry, 15).label(
                        "geometry_geojson"
                    ),
                    SourceObservationModel.confidence,
                    SourceObservationModel.intensity,
                )
                .where(
                    tuple_(
                        SourceObservationModel.source_name,
                        SourceObservationModel.source_record_id,
                    ).in_(identities),
                    SourceObservationModel.observation_kind == "fire",
                )
                .order_by(
                    SourceObservationModel.observed_at,
                    SourceObservationModel.source_name,
                    SourceObservationModel.source_record_id,
                )
            )
        ).all()
        if len(rows) != len(set(identities)):
            raise ValueError("snapshot detection identities must resolve uniquely")
        detections: list[DetectionReadModel] = []
        for row in rows:
            if row.confidence is None:
                raise ValueError("stored fire detection confidence is required")
            detections.append(
                DetectionReadModel(
                    source_name=row.source_name,
                    source_record_id=row.source_record_id,
                    observed_at=_utc(row.observed_at, "stored detection timestamp"),
                    geometry=_json_object(
                        json.loads(row.geometry_geojson), "detection geometry"
                    ),
                    confidence=row.confidence,
                    intensity=row.intensity,
                )
            )
        return tuple(detections)


def _latest_snapshot_versions() -> Subquery:
    return (
        select(
            IncidentSnapshotModel.incident_id,
            IncidentSnapshotModel.snapshot_version,
        )
        .distinct(IncidentSnapshotModel.incident_id)
        .order_by(
            IncidentSnapshotModel.incident_id,
            IncidentSnapshotModel.snapshot_version.desc(),
        )
        .subquery()
    )


def _parse_incident_id(incident_id: str | UUID) -> tuple[str, UUID]:
    requested_id = str(incident_id)
    try:
        return requested_id, UUID(requested_id)
    except (AttributeError, ValueError):
        raise _incident_not_found(requested_id) from None


def _incident_not_found(incident_id: str) -> ReadModelNotFound:
    return ReadModelNotFound("incident", incident_id)


def _risk(value: object) -> RiskReadModel:
    risk = _mapping(value, "risk")
    factors = _sequence(risk.get("factors"), "risk factors")
    contributions: list[RiskContributionReadModel] = []
    for item in factors:
        factor = _mapping(item, "risk factor")
        contributions.append(
            RiskContributionReadModel(
                name=_string(factor.get("name"), "risk factor name"),
                raw_value=freeze_json_value(factor.get("raw")),
                normalized_value=_number(
                    factor.get("normalized_value"), "normalized risk value"
                ),
                weight=_number(factor.get("weight"), "risk weight"),
                contribution=_number(factor.get("contribution"), "risk contribution"),
            )
        )
    return RiskReadModel(
        score=_number(risk.get("score"), "risk score"),
        algorithm_version=_string(risk.get("config_version"), "risk algorithm version"),
        contributions=tuple(contributions),
    )


def _detailed_risk(value: object) -> DetailedRiskReadModel:
    risk = _mapping(value, "risk")
    summary = _risk(value)
    return DetailedRiskReadModel(
        score=summary.score,
        algorithm_version=summary.algorithm_version,
        contributions=summary.contributions,
        configuration=_json_object(risk.get("config"), "risk configuration"),
    )


def _assets(value: object) -> tuple[ExposedAssetReadModel, ...]:
    assets: list[ExposedAssetReadModel] = []
    for item in _sequence(value, "snapshot assets"):
        asset = _mapping(item, "snapshot asset")
        assets.append(
            ExposedAssetReadModel(
                asset_id=_string(asset.get("asset_id"), "asset ID"),
                asset_kind=_string(asset.get("asset_kind"), "asset kind"),
                name=_string(asset.get("name"), "asset name"),
                population=_optional_integer(asset.get("population"), "population"),
                capacity=_optional_integer(asset.get("capacity"), "asset capacity"),
                source_name=_optional_string(
                    asset.get("source_name"), "asset source name"
                ),
                source_version=_optional_string(
                    asset.get("source_version"), "asset source version"
                ),
                geometry=_json_object(asset.get("geometry_geojson"), "asset geometry"),
                distance_meters=_number(asset.get("distance_meters"), "asset distance"),
                bearing_degrees=_optional_number(
                    asset.get("bearing_degrees"), "asset bearing"
                ),
            )
        )
    return tuple(assets)


def _simulated_resources(value: object) -> tuple[SimulatedResourceReadModel, ...]:
    resources: list[SimulatedResourceReadModel] = []
    for item in _sequence(value, "snapshot resources"):
        resource = _mapping(item, "snapshot resource")
        metadata = _mapping(resource.get("raw_metadata"), "resource metadata")
        if metadata.get("simulated") is not True:
            continue
        capabilities = tuple(
            _string(capability, "resource capability")
            for capability in _sequence(
                resource.get("capabilities"), "resource capabilities"
            )
        )
        resources.append(
            SimulatedResourceReadModel(
                resource_id=_string(resource.get("resource_id"), "resource ID"),
                resource_type=_string(resource.get("resource_type"), "resource type"),
                capabilities=capabilities,
                capacity=_integer(resource.get("capacity"), "resource capacity"),
                available=_boolean(resource.get("available"), "resource availability"),
                status=_string(resource.get("status"), "resource status"),
                geometry=_json_object(
                    resource.get("geometry_geojson"), "resource geometry"
                ),
            )
        )
    return tuple(resources)


def _incident_name(state: Mapping[str, object], incident_id: UUID) -> str:
    name = state.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return f"Incident {str(incident_id)[:8]}"


def _identity(value: object, field: str) -> tuple[str, str]:
    identity = _string(value, field)
    source_name, separator, source_record_id = identity.partition(":")
    if not separator or not source_name or not source_record_id:
        raise ValueError(f"stored {field} must be source:record-id")
    return source_name, source_record_id


def _json_object(value: object, field: str) -> FrozenJsonObject:
    return freeze_json_object(dict(_mapping(value, field)))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"stored {field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"stored {field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"stored {field} must be a nonblank string")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"stored {field} must be a number")
    return float(value)


def _optional_number(value: object, field: str) -> float | None:
    return None if value is None else _number(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"stored {field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"stored {field} must be a boolean")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"stored {field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"stored {field} must be an ISO timestamp") from None
    return _utc(parsed, f"stored {field}")


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return value.astimezone(UTC)


def _snapshot_freshness(
    state: Mapping[str, object],
    observed_at: datetime,
    stale_after_seconds: float,
) -> Freshness:
    reference_at = _timestamp(state.get("reference_at"), "snapshot reference")
    age_seconds = (reference_at - observed_at).total_seconds()
    return "fresh" if age_seconds <= stale_after_seconds else "stale"


@dataclass(frozen=True, slots=True)
class _SourcePolicy:
    poll_interval_seconds: float
    stale_after_seconds: float


class SqlAlchemySourceQueryService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        clock: UtcClock,
    ) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock

    async def list_statuses(self) -> tuple[SourceStatusReadModel, ...]:
        rows = (
            await self._session.scalars(
                select(SourceStatusModel).order_by(SourceStatusModel.source_name)
            )
        ).all()
        reference_at = _utc(self._clock(), "API clock")
        return tuple(self._status(row, reference_at) for row in rows)

    def _status(
        self,
        row: SourceStatusModel,
        reference_at: datetime,
    ) -> SourceStatusReadModel:
        policy = _source_policy(row.source_name, self._settings)
        attempted_at = _utc(row.last_attempted_at, "source last attempt")
        last_success_at = (
            None
            if row.last_success_at is None
            else _utc(row.last_success_at, "source last success")
        )
        return SourceStatusReadModel(
            source_name=row.source_name,
            last_attempted_at=attempted_at,
            last_success_at=last_success_at,
            next_retry_at=(
                None
                if policy is None
                else attempted_at + timedelta(seconds=policy.poll_interval_seconds)
            ),
            freshness=_source_freshness(
                outcome=row.outcome,
                last_success_at=last_success_at,
                reference_at=reference_at,
                policy=policy,
            ),
            accepted_count=row.accepted_count,
            deduplicated_count=row.deduplicated_count,
            quarantined_count=row.quarantined_count,
            last_error_code=_safe_error_code(row.error_message),
        )


def _source_policy(source_name: str, settings: Settings) -> _SourcePolicy | None:
    normalized = source_name.strip().lower()
    if normalized in {"nasa_firms", "firms"}:
        return _SourcePolicy(
            poll_interval_seconds=settings.firms_poll_interval_seconds,
            stale_after_seconds=settings.risk_fire_freshness_seconds,
        )
    if normalized in {"nws", "noaa", "noaa_nws"}:
        return _SourcePolicy(
            poll_interval_seconds=settings.nws_poll_interval_seconds,
            stale_after_seconds=settings.risk_weather_freshness_seconds,
        )
    return None


def _source_freshness(
    *,
    outcome: str,
    last_success_at: datetime | None,
    reference_at: datetime,
    policy: _SourcePolicy | None,
) -> Freshness:
    if last_success_at is None or policy is None:
        return "unavailable"
    if outcome != "success":
        return "stale"
    age_seconds = (reference_at - last_success_at).total_seconds()
    return "fresh" if age_seconds <= policy.stale_after_seconds else "stale"


def _safe_error_code(error_message: str | None) -> str | None:
    if error_message is None:
        return None
    normalized = error_message.casefold()
    if "unavailable" in normalized:
        return "source_unavailable"
    if "timeout" in normalized or "timed out" in normalized:
        return "source_timeout"
    if "validation" in normalized or "invalid" in normalized:
        return "source_validation_error"
    return "source_processing_error"
