from typing import Annotated

from fastapi import APIRouter, Depends

from wildfireops.api.dependencies import (
    IncidentQueryService,
    get_incident_query_service,
)
from wildfireops.api.schemas.incidents import (
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentTimelineResponse,
)


router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentListResponse:
    return IncidentListResponse(items=await service.list_incidents())


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: str,
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentDetailResponse:
    return await service.get_incident(incident_id)


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineResponse)
async def get_incident_timeline(
    incident_id: str,
    service: Annotated[IncidentQueryService, Depends(get_incident_query_service)],
) -> IncidentTimelineResponse:
    return IncidentTimelineResponse(items=await service.get_timeline(incident_id))
