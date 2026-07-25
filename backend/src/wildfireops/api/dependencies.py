from collections.abc import AsyncIterator, Mapping

from fastapi import Request

from wildfireops.api.event_bus import EventBus
from wildfireops.application.read_models import (
    IncidentQueryService,
    ReadServiceProvider,
    SourceQueryService,
)
from wildfireops.application.commands import CommandServiceProvider
from wildfireops.decision.commands import AuditQueryService, DecisionCommandService
from wildfireops.decision.recommendations import RecommendationService
from wildfireops.decision.scenarios import ScenarioService
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.application.exercise_planning import ExercisePlanningService
from wildfireops.application.exercises import ExerciseQueryService, ExerciseSessionService


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


def get_road_graphs(request: Request) -> Mapping[str, RoadGraph]:
    return request.app.state.graphs


async def get_scenario_service(request: Request) -> AsyncIterator[ScenarioService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.scenarios() as service:
        yield service


async def get_recommendation_service(
    request: Request,
) -> AsyncIterator[RecommendationService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.recommendations() as service:
        yield service


async def get_decision_service(
    request: Request,
) -> AsyncIterator[DecisionCommandService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.decisions() as service:
        yield service


async def get_audit_service(request: Request) -> AsyncIterator[AuditQueryService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.audits() as service:
        yield service


async def get_exercise_session_service(
    request: Request,
) -> AsyncIterator[ExerciseSessionService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.exercise_sessions() as service:
        yield service


async def get_exercise_planning_service(
    request: Request,
) -> AsyncIterator[ExercisePlanningService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.exercise_planning() as service:
        yield service


async def get_exercise_query_service(
    request: Request,
) -> AsyncIterator[ExerciseQueryService]:
    provider: CommandServiceProvider = request.app.state.command_service_provider
    async with provider.exercise_queries() as service:
        yield service
