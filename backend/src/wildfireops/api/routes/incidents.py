from typing import Annotated

from fastapi import APIRouter, Depends

from wildfireops.api.dependencies import get_incident_query_service
from wildfireops.api.mappers.incidents import (
    incident_detail,
    incident_summary,
    timeline_frame,
)
from wildfireops.api.schemas.incidents import (
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentTimelineResponse,
)
from wildfireops.application.read_models import IncidentQueryService


router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentListResponse:
    models = await service.list_incidents()
    return IncidentListResponse(items=tuple(incident_summary(item) for item in models))


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: str,
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentDetailResponse:
    return incident_detail(await service.get_incident(incident_id))


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineResponse)
async def get_incident_timeline(
    incident_id: str,
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentTimelineResponse:
    models = await service.get_timeline(incident_id)
    return IncidentTimelineResponse(
        items=tuple(timeline_frame(item) for item in models)
    )
