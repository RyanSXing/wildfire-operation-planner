from typing import Literal

from wildfireops.api.schemas.incidents import ApiModel


class RoadGraphSummaryResponse(ApiModel):
    graph_version: str
    edge_count: int


class DecisionContextResponse(ApiModel):
    incident_id: str
    default_graph_version: str | None
    available_graphs: tuple[RoadGraphSummaryResponse, ...]


class LineStringGeometryResponse(ApiModel):
    type: Literal["LineString"] = "LineString"
    coordinates: tuple[tuple[float, float], ...]


class RoadEdgeResponse(ApiModel):
    edge_id: str
    label: str
    geometry: LineStringGeometryResponse | None
    travel_minutes: float
    distance_meters: float


class RoadEdgeListResponse(ApiModel):
    items: tuple[RoadEdgeResponse, ...]
    total: int
    missing_edge_ids: tuple[str, ...]
