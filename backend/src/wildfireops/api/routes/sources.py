from typing import Annotated

from fastapi import APIRouter, Depends

from wildfireops.api.dependencies import get_source_query_service
from wildfireops.api.schemas.sources import SourceStatusListResponse
from wildfireops.api.services.sources import SourceQueryService


router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/status", response_model=SourceStatusListResponse)
async def list_source_statuses(
    service: Annotated[SourceQueryService, Depends(get_source_query_service)],
) -> SourceStatusListResponse:
    return SourceStatusListResponse(items=await service.list_statuses())
