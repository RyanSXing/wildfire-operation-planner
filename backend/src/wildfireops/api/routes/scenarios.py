from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header
from pydantic import JsonValue

from wildfireops.api.command_errors import command_api_error
from wildfireops.api.dependencies import (
    get_recommendation_service,
    get_scenario_service,
)
from wildfireops.api.schemas.scenarios import (
    ObjectiveComponentsResponse,
    RecommendationAssignmentResponse,
    RecommendationCreateRequest,
    RecommendationOutcomeResponse,
    RecommendationResponse,
    ResourceOverrideInput,
    RoadClosureInput,
    RouteResponse,
    ScenarioCreateRequest,
    ScenarioVersionCreateRequest,
    ScenarioVersionResponse,
    WeatherOverrideInput,
)
from wildfireops.api.schemas.incidents import (
    RiskContributionResponse,
    RiskResponse,
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
        outcome=recommendation_outcome(stored),
    )


def recommendation_outcome(
    stored: StoredRecommendation,
) -> RecommendationOutcomeResponse:
    inputs = _stored_object(stored.request_inputs, "request inputs")
    scenario_risk = _scenario_risk(
        _stored_required(inputs, "risk_breakdown", "request inputs")
    )
    if scenario_risk.algorithm_version != stored.risk_version:
        raise ValueError("stored risk versions do not match")

    resources = _stored_resources(
        _stored_required(inputs, "resources", "request inputs")
    )
    demands = _stored_demands(_stored_required(inputs, "demands", "request inputs"))
    assigned_destinations: set[str] = set()
    total_travel_minutes = 0.0
    for assignment in stored.assignments:
        resource_id = _stored_text(assignment.resource_id, "assignment resource ID")
        destination_id = _stored_text(
            assignment.destination_id,
            "assignment destination ID",
        )
        if resource_id not in resources or destination_id not in demands:
            raise ValueError("stored assignment references unknown input")
        if not resources[resource_id]:
            raise ValueError("stored assignment uses an unavailable resource")
        assigned_destinations.add(destination_id)
        total_travel_minutes += _stored_nonnegative_number(
            assignment.travel_minutes,
            "assignment travel minutes",
        )

    uncovered_destinations = {
        _stored_text(destination_id, "uncovered destination ID")
        for destination_id in stored.uncovered_destination_ids
    }
    if (
        assigned_destinations & uncovered_destinations
        or assigned_destinations | uncovered_destinations != set(demands)
    ):
        raise ValueError("stored recommendation coverage is inconsistent")

    routes_by_destination: dict[str, list[str]] = {
        destination_id: [] for destination_id in demands
    }
    route_pairs: set[tuple[str, str]] = set()
    for raw_route in _stored_sequence(
        _stored_required(inputs, "candidate_routes", "request inputs"),
        "candidate routes",
    ):
        candidate = _stored_object(raw_route, "candidate route")
        resource_id = _stored_text(
            _stored_required(candidate, "resource_id", "candidate route"),
            "candidate route resource ID",
        )
        destination_id = _stored_text(
            _stored_required(candidate, "destination_id", "candidate route"),
            "candidate route destination ID",
        )
        if resource_id not in resources or destination_id not in demands:
            raise ValueError("stored candidate route references unknown input")
        pair = (resource_id, destination_id)
        if pair in route_pairs:
            raise ValueError("stored candidate routes are duplicated")
        route_pairs.add(pair)
        route = _stored_object(
            _stored_required(candidate, "route", "candidate route"),
            "candidate route payload",
        )
        status = _stored_text(
            _stored_required(route, "status", "candidate route payload"),
            "candidate route status",
        )
        if status not in {"reachable", "unreachable"}:
            raise ValueError("stored candidate route status is invalid")
        routes_by_destination[destination_id].append(status)

    return RecommendationOutcomeResponse(
        scenario_risk=scenario_risk,
        weighted_risk_covered=round(
            sum(demands[item] for item in assigned_destinations),
            6,
        ),
        weighted_risk_uncovered=round(
            sum(demands[item] for item in uncovered_destinations),
            6,
        ),
        total_travel_minutes=round(total_travel_minutes, 6),
        unreachable_destination_ids=tuple(
            sorted(
                destination_id
                for destination_id, statuses in routes_by_destination.items()
                if not statuses or all(status == "unreachable" for status in statuses)
            )
        ),
        unavailable_resource_ids=tuple(
            sorted(
                resource_id
                for resource_id, available in resources.items()
                if not available
            )
        ),
    )


def _scenario_risk(value: object) -> RiskResponse:
    risk = _stored_object(value, "risk breakdown")
    factors = tuple(
        _risk_contribution(item)
        for item in _stored_sequence(
            _stored_required(risk, "factors", "risk breakdown"),
            "risk factors",
        )
    )
    return RiskResponse(
        score=_stored_nonnegative_number(
            _stored_required(risk, "score", "risk breakdown"),
            "risk score",
        ),
        algorithm_version=_stored_text(
            _stored_required(risk, "config_version", "risk breakdown"),
            "risk config version",
        ),
        contributions=factors,
    )


def _risk_contribution(value: object) -> RiskContributionResponse:
    factor = _stored_object(value, "risk factor")
    return RiskContributionResponse(
        name=_stored_text(
            _stored_required(factor, "name", "risk factor"),
            "risk factor name",
        ),
        raw_value=cast(
            JsonValue,
            _stored_required(factor, "raw", "risk factor"),
        ),
        normalized_value=_stored_number(
            _stored_required(factor, "normalized_value", "risk factor"),
            "normalized risk value",
        ),
        weight=_stored_number(
            _stored_required(factor, "weight", "risk factor"),
            "risk weight",
        ),
        contribution=_stored_number(
            _stored_required(factor, "contribution", "risk factor"),
            "risk contribution",
        ),
    )


def _stored_resources(value: object) -> dict[str, bool]:
    resources: dict[str, bool] = {}
    for raw_resource in _stored_sequence(value, "resources"):
        resource = _stored_object(raw_resource, "resource")
        resource_id = _stored_text(
            _stored_required(resource, "resource_id", "resource"),
            "resource ID",
        )
        available = _stored_required(resource, "available", "resource")
        if resource_id in resources or not isinstance(available, bool):
            raise ValueError("stored resources are invalid")
        resources[resource_id] = available
    return resources


def _stored_demands(value: object) -> dict[str, float]:
    demands: dict[str, float] = {}
    for raw_demand in _stored_sequence(value, "demands"):
        demand = _stored_object(raw_demand, "demand")
        destination_id = _stored_text(
            _stored_required(demand, "destination_id", "demand"),
            "destination ID",
        )
        if destination_id in demands:
            raise ValueError("stored demands are duplicated")
        demands[destination_id] = _stored_nonnegative_number(
            _stored_required(demand, "weighted_risk", "demand"),
            "weighted risk",
        )
    return demands


def _stored_object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"stored {field} must be an object")
    return value


def _stored_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"stored {field} must be an array")
    return value


def _stored_required(
    value: Mapping[str, object],
    key: str,
    field: str,
) -> object:
    if key not in value:
        raise ValueError(f"stored {field} is missing {key}")
    return value[key]


def _stored_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"stored {field} must be normalized text")
    return value


def _stored_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"stored {field} must be a finite number")
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"stored {field} must be a finite number")
    return parsed


def _stored_nonnegative_number(value: object, field: str) -> float:
    parsed = _stored_number(value, field)
    if parsed < 0:
        raise ValueError(f"stored {field} must be nonnegative")
    return parsed


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
