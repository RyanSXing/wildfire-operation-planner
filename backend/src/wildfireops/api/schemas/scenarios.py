from pydantic import Field, JsonValue

from wildfireops.api.schemas.incidents import ApiModel


class RoadClosureInput(ApiModel):
    edge_id: str


class WeatherOverrideInput(ApiModel):
    wind_speed_mps: float
    wind_direction_degrees: float


class ResourceOverrideInput(ApiModel):
    resource_id: str
    available: bool


class ScenarioCreateRequest(ApiModel):
    graph_version: str
    objective: str
    name: str | None = None
    algorithm_config_version: str = "scenario-v1"


class ScenarioVersionCreateRequest(ApiModel):
    road_closures: tuple[RoadClosureInput, ...] | None = None
    weather_overrides: tuple[WeatherOverrideInput, ...] | None = None
    resource_overrides: tuple[ResourceOverrideInput, ...] | None = None


class ScenarioVersionResponse(ApiModel):
    id: str
    scenario_id: str
    incident_id: str
    incident_snapshot_id: str
    version: int
    graph_version: str
    road_closures: tuple[RoadClosureInput, ...]
    weather_overrides: tuple[WeatherOverrideInput, ...]
    resource_overrides: tuple[ResourceOverrideInput, ...]


class RecommendationCreateRequest(ApiModel):
    max_response_minutes: int = Field(default=30, ge=0)
    max_solver_seconds: float = Field(default=2.0, gt=0)


class RouteResponse(ApiModel):
    status: str
    edge_ids: tuple[str, ...]
    distance_meters: float
    travel_minutes: float
    graph_version: str
    closure_hash: str


class RecommendationAssignmentResponse(ApiModel):
    resource_id: str
    destination_id: str
    route: RouteResponse
    travel_minutes: float
    capacity: int


class ObjectiveComponentsResponse(ApiModel):
    travel_cost: int
    uncovered_risk_penalty: int
    objective_value: int


class RecommendationResponse(ApiModel):
    id: str
    scenario_version_id: str
    incident_snapshot_id: str
    assignments: tuple[RecommendationAssignmentResponse, ...]
    uncovered_destination_ids: tuple[str, ...]
    objective_components: ObjectiveComponentsResponse
    solver_status: str
    runtime_milliseconds: int
    graph_version: str
    risk_version: str
    algorithm_version: str
    input_version: str
    source_versions: dict[str, JsonValue]
    explanation: dict[str, JsonValue]
