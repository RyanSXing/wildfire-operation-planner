from typing import Annotated

from fastapi import APIRouter, Depends

from wildfireops.api.dependencies import get_source_query_service
from wildfireops.api.mappers.sources import source_status
from wildfireops.api.schemas.sources import SourceStatusListResponse
from wildfireops.application.read_models import SourceQueryService


router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/status", response_model=SourceStatusListResponse)
async def list_source_statuses(
    service: Annotated[SourceQueryService, Depends(get_source_query_service)],
) -> SourceStatusListResponse:
    models = await service.list_statuses()
    return SourceStatusListResponse(items=tuple(source_status(item) for item in models))
