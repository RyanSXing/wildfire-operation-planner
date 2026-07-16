from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.api.services.incidents import IncidentQueryService
from wildfireops.api.services.sources import SourceQueryService
from wildfireops.api.event_bus import EventBus


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_incident_query_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IncidentQueryService:
    return IncidentQueryService(
        session=session,
        settings=request.app.state.settings,
    )


def get_source_query_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SourceQueryService:
    return SourceQueryService(
        session=session,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
    )


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_event_heartbeat_seconds(request: Request) -> float:
    return request.app.state.event_heartbeat_seconds
