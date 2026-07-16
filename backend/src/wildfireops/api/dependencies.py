from collections.abc import AsyncIterator

from fastapi import Request

from wildfireops.api.event_bus import EventBus
from wildfireops.application.read_models import (
    IncidentQueryService,
    ReadServiceProvider,
    SourceQueryService,
)


async def get_incident_query_service(
    request: Request,
) -> AsyncIterator[IncidentQueryService]:
    provider: ReadServiceProvider = request.app.state.read_service_provider
    async with provider.incidents() as service:
        yield service


async def get_source_query_service(
    request: Request,
) -> AsyncIterator[SourceQueryService]:
    provider: ReadServiceProvider = request.app.state.read_service_provider
    async with provider.sources() as service:
        yield service


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_event_heartbeat_seconds(request: Request) -> float:
    return request.app.state.event_heartbeat_seconds
