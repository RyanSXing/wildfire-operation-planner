from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from wildfireops.api.dependencies import (
    get_incident_query_service,
    get_road_graphs,
)
from wildfireops.api.errors import ApiError
from wildfireops.api.schemas.road_graphs import (
    DecisionContextResponse,
    LineStringGeometryResponse,
    RoadEdgeListResponse,
    RoadEdgeResponse,
    RoadGraphSummaryResponse,
)
from wildfireops.application.read_models import IncidentQueryService
from wildfireops.geospatial.road_graph import RoadEdge, RoadGraph


router = APIRouter(tags=["road-graphs"])


@router.get(
    "/api/incidents/{incident_id}/decision-context",
    response_model=DecisionContextResponse,
)
async def get_decision_context(
    incident_id: str,
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
    graphs: Annotated[Mapping[str, RoadGraph], Depends(get_road_graphs)],
) -> DecisionContextResponse:
    incident = await service.get_incident(incident_id)
    available = tuple(
        RoadGraphSummaryResponse(
            graph_version=graph_version,
            edge_count=len(graph.edge_ids),
        )
        for graph_version, graph in sorted(graphs.items())
    )
    return DecisionContextResponse(
        incident_id=incident.id,
        default_graph_version=(available[0].graph_version if available else None),
        available_graphs=available,
    )


@router.get(
    "/api/road-graphs/{graph_version}/edges",
    response_model=RoadEdgeListResponse,
)
async def get_road_edges(
    graph_version: str,
    graphs: Annotated[Mapping[str, RoadGraph], Depends(get_road_graphs)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    edge_ids: Annotated[list[str] | None, Query(alias="edgeId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RoadEdgeListResponse:
    graph = graphs.get(graph_version)
    if graph is None:
        raise ApiError(
            status_code=404,
            code="road_graph_not_found",
            message="Road graph was not found",
            details={"graphVersion": graph_version},
        )

    if edge_ids is not None:
        if len(edge_ids) > 200:
            raise ApiError(
                status_code=422,
                code="too_many_edge_ids",
                message="At most 200 edge IDs are allowed",
            )
        requested = tuple(sorted(set(edge_ids)))
        catalog = {edge.edge_id: edge for edge in graph.road_edges}
        matched = tuple(catalog[edge_id] for edge_id in requested if edge_id in catalog)
        missing = tuple(edge_id for edge_id in requested if edge_id not in catalog)
        return _edge_list(matched, total=len(matched), missing=missing)

    term = "" if q is None else q.strip().casefold()
    matched = tuple(
        edge
        for edge in graph.road_edges
        if not term or term in edge.label.casefold() or term in edge.edge_id.casefold()
    )
    return _edge_list(matched[:limit], total=len(matched))


def _edge_list(
    edges: tuple[RoadEdge, ...],
    *,
    total: int,
    missing: tuple[str, ...] = (),
) -> RoadEdgeListResponse:
    return RoadEdgeListResponse(
        items=tuple(_edge_response(edge) for edge in edges),
        total=total,
        missing_edge_ids=missing,
    )


def _edge_response(edge: RoadEdge) -> RoadEdgeResponse:
    return RoadEdgeResponse(
        edge_id=edge.edge_id,
        label=edge.label,
        geometry=(
            None
            if edge.geometry is None
            else LineStringGeometryResponse(coordinates=edge.geometry)
        ),
        travel_minutes=edge.travel_minutes,
        distance_meters=edge.distance_meters,
    )
