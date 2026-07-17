from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header
from pydantic import JsonValue

from wildfireops.api.command_errors import command_api_error
from wildfireops.api.dependencies import (
    get_recommendation_service,
    get_scenario_service,
)
from wildfireops.api.schemas.scenarios import (
    RecommendationAssignmentResponse,
    RecommendationCreateRequest,
    RecommendationResponse,
    ObjectiveComponentsResponse,
    ResourceOverrideInput,
    RoadClosureInput,
    RouteResponse,
    ScenarioCreateRequest,
    ScenarioVersionCreateRequest,
    ScenarioVersionResponse,
    WeatherOverrideInput,
)
from wildfireops.decision.recommendations import (
    RecommendationError,
    RecommendationRequest,
    RecommendationService,
    StoredRecommendation,
    StoredRecommendationAssignment,
)
from wildfireops.decision.scenarios import (
    ScenarioError,
    ScenarioService,
    ScenarioValidationError,
)
from wildfireops.domain.scenarios import (
    ResourceOverride,
    RoadClosure,
    WeatherOverride,
)
from wildfireops.domain.scenario_versions import StoredScenarioVersion


router = APIRouter(tags=["scenarios"])
_ACTOR_ID = "demo-operator"


@router.post(
    "/api/incidents/{incident_id}/scenarios",
    response_model=ScenarioVersionResponse,
    status_code=201,
)
async def create_scenario(
    incident_id: str,
    body: ScenarioCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ScenarioService, Depends(get_scenario_service)],
) -> ScenarioVersionResponse:
    try:
        stored = await service.create(
            incident_id=incident_id,
            graph_version=body.graph_version,
            name=body.name,
            objective=body.objective,
            author_id=_ACTOR_ID,
            algorithm_config_version=body.algorithm_config_version,
            idempotency_key=idempotency_key,
        )
    except ScenarioError as error:
        raise command_api_error(error) from error
    return _scenario_response(stored)


@router.post(
    "/api/scenarios/{scenario_id}/versions",
    response_model=ScenarioVersionResponse,
    status_code=201,
)
async def create_scenario_version(
    scenario_id: str,
    body: ScenarioVersionCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ScenarioService, Depends(get_scenario_service)],
) -> ScenarioVersionResponse:
    try:
        stored = await service.add_version(
            scenario_id=scenario_id,
            created_by=_ACTOR_ID,
            idempotency_key=idempotency_key,
            road_closures=(
                None
                if body.road_closures is None
                else tuple(RoadClosure(item.edge_id) for item in body.road_closures)
            ),
            weather_overrides=(
                None
                if body.weather_overrides is None
                else tuple(
                    WeatherOverride(
                        item.wind_speed_mps,
                        item.wind_direction_degrees,
                    )
                    for item in body.weather_overrides
                )
            ),
            resource_overrides=(
                None
                if body.resource_overrides is None
                else tuple(
                    ResourceOverride(item.resource_id, item.available)
                    for item in body.resource_overrides
                )
            ),
        )
    except (ScenarioError, ValueError) as error:
        if isinstance(error, ScenarioError):
            raise command_api_error(error) from error
        raise command_api_error(ScenarioValidationError(str(error))) from error
    return _scenario_response(stored)


@router.post(
    "/api/scenario-versions/{version_id}/recommendations",
    response_model=RecommendationResponse,
    status_code=201,
)
async def generate_recommendation(
    version_id: str,
    body: RecommendationCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        RecommendationService,
        Depends(get_recommendation_service),
    ],
) -> RecommendationResponse:
    try:
        stored = await service.generate(
            version_id,
            RecommendationRequest(
                max_response_minutes=body.max_response_minutes,
                max_solver_seconds=body.max_solver_seconds,
            ),
            _ACTOR_ID,
            idempotency_key,
        )
    except RecommendationError as error:
        raise command_api_error(error) from error
    return recommendation_response(stored)


def _scenario_response(stored: StoredScenarioVersion) -> ScenarioVersionResponse:
    scenario = stored.scenario
    return ScenarioVersionResponse(
        id=str(stored.version_id),
        scenario_id=scenario.scenario_id,
        incident_id=str(stored.incident_id),
        incident_snapshot_id=scenario.incident_snapshot_id,
        version=scenario.version,
        graph_version=stored.graph_version,
        road_closures=tuple(
            RoadClosureInput(edge_id=item.edge_id) for item in scenario.road_closures
        ),
        weather_overrides=tuple(
            WeatherOverrideInput(
                wind_speed_mps=item.wind_speed_mps,
                wind_direction_degrees=item.wind_direction_degrees,
            )
            for item in scenario.weather_overrides
        ),
        resource_overrides=tuple(
            ResourceOverrideInput(
                resource_id=item.resource_id,
                available=item.available,
            )
            for item in scenario.resource_overrides
        ),
    )


def recommendation_response(stored: StoredRecommendation) -> RecommendationResponse:
    return RecommendationResponse(
        id=str(stored.id),
        scenario_version_id=str(stored.scenario_version_id),
        incident_snapshot_id=str(stored.incident_snapshot_id),
        assignments=tuple(
            recommendation_assignment(item) for item in stored.assignments
        ),
        uncovered_destination_ids=stored.uncovered_destination_ids,
        objective_components=ObjectiveComponentsResponse.model_validate(
            stored.objective_components
        ),
        solver_status=stored.solver_status,
        runtime_milliseconds=stored.runtime_milliseconds,
        graph_version=stored.graph_version,
        risk_version=stored.risk_version,
        algorithm_version=stored.algorithm_version,
        input_version=stored.input_version,
        source_versions=cast(dict[str, JsonValue], dict(stored.source_versions)),
        explanation=cast(dict[str, JsonValue], dict(stored.explanation)),
    )


def recommendation_assignment(
    item: StoredRecommendationAssignment,
) -> RecommendationAssignmentResponse:
    return RecommendationAssignmentResponse(
        resource_id=item.resource_id,
        destination_id=item.destination_id,
        route=RouteResponse.model_validate(item.route),
        travel_minutes=item.travel_minutes,
        capacity=item.capacity,
    )
