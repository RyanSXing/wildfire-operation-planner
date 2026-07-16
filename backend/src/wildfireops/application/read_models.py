from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from wildfireops.domain.observations import FrozenJsonObject, FrozenJsonValue


type Freshness = Literal["fresh", "stale", "unavailable"]


@dataclass(frozen=True, slots=True)
class RiskContributionReadModel:
    name: str
    raw_value: FrozenJsonValue
    normalized_value: float
    weight: float
    contribution: float


@dataclass(frozen=True, slots=True)
class RiskReadModel:
    score: float
    algorithm_version: str
    contributions: tuple[RiskContributionReadModel, ...]


@dataclass(frozen=True, slots=True)
class DetailedRiskReadModel(RiskReadModel):
    configuration: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class DetectionReadModel:
    source_name: str
    source_record_id: str
    observed_at: datetime
    geometry: FrozenJsonObject
    confidence: float
    intensity: float | None


@dataclass(frozen=True, slots=True)
class ExposedAssetReadModel:
    asset_id: str
    asset_kind: str
    name: str
    population: int | None
    capacity: int | None
    source_name: str | None
    source_version: str | None
    geometry: FrozenJsonObject
    distance_meters: float
    bearing_degrees: float | None


@dataclass(frozen=True, slots=True)
class SimulatedResourceReadModel:
    resource_id: str
    resource_type: str
    capabilities: tuple[str, ...]
    capacity: int
    available: bool
    status: str
    geometry: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class IncidentSummaryReadModel:
    id: str
    name: str
    risk: RiskReadModel
    exposed_asset_count: int
    last_observed_at: datetime
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class IncidentDetailReadModel:
    id: str
    name: str
    status: str
    snapshot_id: str
    snapshot_version: int
    geometry: FrozenJsonObject
    first_observed_at: datetime
    last_observed_at: datetime
    freshness: Freshness
    risk: DetailedRiskReadModel
    detections: tuple[DetectionReadModel, ...]
    exposed_assets: tuple[ExposedAssetReadModel, ...]
    simulated_resources: tuple[SimulatedResourceReadModel, ...]
    source_versions: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class TimelineFrameReadModel:
    snapshot_id: str
    snapshot_version: int
    captured_at: datetime
    reference_at: datetime
    last_observed_at: datetime
    geometry: FrozenJsonObject
    risk: RiskReadModel
    detections: tuple[DetectionReadModel, ...]
    exposed_asset_count: int
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class SourceStatusReadModel:
    source_name: str
    last_attempted_at: datetime
    last_success_at: datetime | None
    next_retry_at: datetime | None
    freshness: Freshness
    accepted_count: int
    deduplicated_count: int
    quarantined_count: int
    last_error_code: str | None


class ReadModelNotFound(Exception):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} was not found")
        self.resource = resource
        self.identifier = identifier


class IncidentQueryService(Protocol):
    async def list_incidents(self) -> tuple[IncidentSummaryReadModel, ...]: ...

    async def get_incident(self, incident_id: str) -> IncidentDetailReadModel: ...

    async def get_timeline(
        self, incident_id: str
    ) -> tuple[TimelineFrameReadModel, ...]: ...


class SourceQueryService(Protocol):
    async def list_statuses(self) -> tuple[SourceStatusReadModel, ...]: ...


class ReadServiceProvider(Protocol):
    def incidents(
        self,
    ) -> AbstractAsyncContextManager[IncidentQueryService]: ...

    def sources(self) -> AbstractAsyncContextManager[SourceQueryService]: ...
