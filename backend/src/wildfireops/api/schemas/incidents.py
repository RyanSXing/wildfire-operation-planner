from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from pydantic.alias_generators import to_camel


type Freshness = Literal["fresh", "stale", "unavailable"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class RiskContributionResponse(ApiModel):
    name: str
    raw_value: JsonValue
    normalized_value: float
    weight: float
    contribution: float


class RiskResponse(ApiModel):
    score: float
    algorithm_version: str
    contributions: tuple[RiskContributionResponse, ...]


class DetailedRiskResponse(RiskResponse):
    configuration: dict[str, JsonValue]


class IncidentSummaryResponse(ApiModel):
    id: str
    name: str
    risk: RiskResponse
    exposed_asset_count: int
    last_observed_at: datetime
    freshness: Freshness


class IncidentListResponse(ApiModel):
    items: tuple[IncidentSummaryResponse, ...]


class DetectionResponse(ApiModel):
    source_name: str
    source_record_id: str
    observed_at: datetime
    geometry: dict[str, JsonValue]
    confidence: float
    intensity: float | None


class ExposedAssetResponse(ApiModel):
    asset_id: str
    asset_kind: str
    name: str
    population: int | None
    capacity: int | None
    source_name: str | None
    source_version: str | None
    geometry: dict[str, JsonValue]
    distance_meters: float
    bearing_degrees: float | None


class SimulatedResourceResponse(ApiModel):
    resource_id: str
    resource_type: str
    capabilities: tuple[str, ...]
    capacity: int
    available: bool
    status: str
    geometry: dict[str, JsonValue]
    simulated: Literal[True] = True
    simulation_label: Literal["simulated"] = "simulated"


class IncidentDetailResponse(ApiModel):
    id: str
    name: str
    status: str
    snapshot_id: str
    snapshot_version: int
    geometry: dict[str, JsonValue]
    first_observed_at: datetime
    last_observed_at: datetime
    freshness: Freshness
    risk: DetailedRiskResponse
    detections: tuple[DetectionResponse, ...]
    exposed_assets: tuple[ExposedAssetResponse, ...]
    simulated_resources: tuple[SimulatedResourceResponse, ...]
    source_versions: dict[str, JsonValue]


class TimelineFrameResponse(ApiModel):
    snapshot_id: str
    snapshot_version: int
    captured_at: datetime
    reference_at: datetime
    last_observed_at: datetime
    geometry: dict[str, JsonValue]
    risk: RiskResponse
    detections: tuple[DetectionResponse, ...]
    exposed_asset_count: int
    freshness: Freshness


class IncidentTimelineResponse(ApiModel):
    items: tuple[TimelineFrameResponse, ...]
