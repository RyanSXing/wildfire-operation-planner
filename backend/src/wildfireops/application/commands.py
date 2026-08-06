from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.config import Settings
from wildfireops.decision.commands import AuditQueryService, DecisionCommandService
from wildfireops.decision.optimizer import ALLOCATION_ALGORITHM_VERSION
from wildfireops.decision.recommendations import RecommendationService
from wildfireops.decision.risk import RiskConfig
from wildfireops.decision.scenarios import ScenarioService
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.persistence.decisions import AuditRepository, DecisionRepository
from wildfireops.persistence.recommendations import RecommendationRepository
from wildfireops.persistence.scenarios import ScenarioRepository
from wildfireops.application.exercise_planning import ExercisePlanningService
from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseNotFound,
    ExerciseQueryService,
    ExerciseSessionService,
)
from wildfireops.persistence.exercises import ExerciseRepository
from wildfireops.replay.exercise import ExerciseDefinition, exercise_definition_digest


type SessionFactory = Callable[[], AsyncSession]
type GraphsProvider = Callable[[], Mapping[str, RoadGraph]]
type Clock = Callable[[], datetime]
type Callsign = Callable[[], str]


class CommandServiceProvider:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        graphs: GraphsProvider,
        settings: Settings,
        exercise_definition: ExerciseDefinition | None = None,
        clock: Clock | None = None,
        callsign: Callsign | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._graphs = graphs
        self._risk_config = _risk_config(settings)
        self._exercise_definition = exercise_definition
        self._clock = clock or (lambda: datetime.now(UTC))
        self._callsign = callsign or (lambda: f"EMBER-{uuid4().hex[:8].upper()}")

    @asynccontextmanager
    async def scenarios(self) -> AsyncIterator[ScenarioService]:
        async with self._session_factory() as session:
            async with session.begin():
                yield ScenarioService(
                    graphs=self._graphs(),
                    repository=ScenarioRepository(session),
                )

    @asynccontextmanager
    async def recommendations(self) -> AsyncIterator[RecommendationService]:
        async with self._session_factory() as session:
            async with session.begin():
                yield RecommendationService(
                    graphs=self._graphs(),
                    risk_config=self._risk_config,
                    repository=RecommendationRepository(session),
                    allocation_algorithm_version=ALLOCATION_ALGORITHM_VERSION,
                )

    @asynccontextmanager
    async def decisions(self) -> AsyncIterator[DecisionCommandService]:
        async with self._session_factory() as session:
            async with session.begin():
                yield DecisionCommandService(
                    DecisionRepository(session),
                    graphs=self._graphs(),
                    risk_version=self._risk_config.algorithm_version,
                    allocation_version=ALLOCATION_ALGORITHM_VERSION,
                )

    @asynccontextmanager
    async def audits(self) -> AsyncIterator[AuditQueryService]:
        async with self._session_factory() as session:
            yield AuditQueryService(AuditRepository(session))

    @asynccontextmanager
    async def exercise_sessions(self) -> AsyncIterator[ExerciseSessionService]:
        definition = self._exercise_definition
        if definition is None:
            raise ExerciseNotFound("exercise is not configured")
        async with self._session_factory() as session:
            async with session.begin():
                yield ExerciseSessionService(
                    definition=definition,
                    definition_digest=exercise_definition_digest(definition),
                    repository=ExerciseRepository(session),
                    clock=self._clock,
                    callsign=self._callsign,
                )

    @asynccontextmanager
    async def exercise_planning(self) -> AsyncIterator[ExercisePlanningService]:
        definition = self._exercise_definition
        if definition is None:
            raise ExerciseNotFound("exercise is not configured")
        graph = self._graphs().get(definition.graph_version)
        if graph is None:
            raise ExerciseCommandInvalid("exercise graph is unavailable")
        async with self._session_factory() as session:
            async with session.begin():
                yield self._exercise_planning_service(session, definition, graph)

    @asynccontextmanager
    async def exercise_sandbox_planning(self) -> AsyncIterator[ExercisePlanningService]:
        definition = self._exercise_definition
        if definition is None:
            raise ExerciseNotFound("exercise is not configured")
        graph = self._graphs().get(definition.graph_version)
        if graph is None:
            raise ExerciseCommandInvalid("exercise graph is unavailable")
        async with self._session_factory() as session:
            await session.connection(
                execution_options={
                    "isolation_level": "SERIALIZABLE",
                    "postgresql_readonly": True,
                }
            )
            yield self._exercise_planning_service(session, definition, graph)

    @asynccontextmanager
    async def exercise_queries(self) -> AsyncIterator[ExerciseQueryService]:
        definition = self._exercise_definition
        if definition is None:
            raise ExerciseNotFound("exercise is not configured")
        async with self._session_factory() as session:
            yield ExerciseQueryService(
                definition=definition,
                definition_digest=exercise_definition_digest(definition),
                repository=ExerciseRepository(session),
                clock=self._clock,
            )

    def _exercise_planning_service(
        self,
        session: AsyncSession,
        definition: ExerciseDefinition,
        graph: RoadGraph,
    ) -> ExercisePlanningService:
        digest = exercise_definition_digest(definition)
        repository = ExerciseRepository(session)
        return ExercisePlanningService(
            definition=definition,
            definition_digest=digest,
            graph=graph,
            repository=repository,
            session_service=ExerciseSessionService(
                definition=definition,
                definition_digest=digest,
                repository=repository,
                clock=self._clock,
                callsign=self._callsign,
            ),
            clock=self._clock,
        )


def _risk_config(settings: Settings) -> RiskConfig:
    return RiskConfig(
        algorithm_version=settings.risk_algorithm_version,
        proximity_weight=settings.risk_proximity_weight,
        population_weight=settings.risk_population_weight,
        critical_facilities_weight=settings.risk_critical_facilities_weight,
        wind_alignment_weight=settings.risk_wind_alignment_weight,
        detection_confidence_weight=settings.risk_detection_confidence_weight,
        source_freshness_weight=settings.risk_source_freshness_weight,
        population_saturation=settings.risk_population_saturation,
        critical_facility_saturation_count=(
            settings.risk_critical_facility_saturation_count
        ),
        wind_speed_saturation_mps=settings.risk_wind_speed_saturation_mps,
        fire_freshness_seconds=settings.risk_fire_freshness_seconds,
        weather_freshness_seconds=settings.risk_weather_freshness_seconds,
        weather_search_radius_meters=settings.risk_weather_search_radius_meters,
    )
