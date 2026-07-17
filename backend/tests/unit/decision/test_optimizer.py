import json
from dataclasses import replace
from math import inf, nan

import pytest

from wildfireops.decision.optimizer import (
    Assignment,
    CandidateRoute,
    OptimizationRequest,
    OptimizationResult,
    solve_allocation,
)
from wildfireops.decision.explanations import explain_result
from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


def _resource(
    resource_id: str,
    *,
    capabilities: frozenset[str] = frozenset({"engine"}),
    capacity: int = 1,
    available: bool = True,
) -> ResourceUnit:
    return ResourceUnit(resource_id, capabilities, capacity, available, -121.6, 39.8)


def _demand(
    destination_id: str,
    *,
    capability: str = "engine",
    capacity: int = 1,
    risk: float = 50.0,
) -> DemandPoint:
    return DemandPoint(destination_id, capability, capacity, risk, -121.5, 39.9)


def _route(
    travel_minutes: float,
    status: RouteStatus = RouteStatus.REACHABLE,
) -> RouteResult:
    return RouteResult(status, (), 0.0, travel_minutes, "graph-v1", "closures-v1")


def _candidate(
    resource_id: str,
    destination_id: str,
    travel_minutes: float,
    status: RouteStatus = RouteStatus.REACHABLE,
) -> CandidateRoute:
    return CandidateRoute(
        resource_id,
        destination_id,
        _route(travel_minutes, status),
    )


def _example_request() -> OptimizationRequest:
    return OptimizationRequest(
        resources=(_resource("engine-far"), _resource("engine-close")),
        demands=(
            _demand("low-risk", capacity=2, risk=20),
            _demand("high-risk", risk=90),
        ),
        routes=(
            _candidate("engine-far", "low-risk", 9),
            _candidate("engine-close", "low-risk", 8),
            _candidate("engine-far", "high-risk", 20),
            _candidate("engine-close", "high-risk", 5),
        ),
        max_response_minutes=30,
    )


def test_solver_deterministically_covers_highest_risk_demand() -> None:
    result = solve_allocation(_example_request())

    assert result.status == "OPTIMAL"
    assert result.assignments == (Assignment("engine-close", "high-risk", 5, 1),)
    assert result.uncovered_destination_ids == ("low-risk",)
    assert result.unassigned_resource_ids == ("engine-far",)
    assert result.travel_cost == 5
    assert result.uncovered_risk_penalty == 200
    assert result.objective_value == 205


def test_exact_float_time_controls_eligibility_and_ceiling_minutes_control_cost() -> (
    None
):
    resource = _resource("engine")
    demand = _demand("community", risk=100)

    too_slow = solve_allocation(
        OptimizationRequest(
            (resource,),
            (demand,),
            (_candidate("engine", "community", 10.01),),
            max_response_minutes=10,
        )
    )
    eligible = solve_allocation(
        OptimizationRequest(
            (resource,),
            (demand,),
            (_candidate("engine", "community", 10.01),),
            max_response_minutes=11,
        )
    )

    assert too_slow.assignments == ()
    assert too_slow.uncovered_destination_ids == ("community",)
    assert eligible.assignments[0].travel_minutes == 10.01
    assert eligible.travel_cost == 11


def test_normalized_risk_penalty_uses_deterministic_integer_rounding() -> None:
    result = solve_allocation(
        OptimizationRequest(
            resources=(),
            demands=(_demand("community", risk=33.35),),
            routes=(),
            max_response_minutes=30,
        )
    )

    assert result.uncovered_risk_penalty == 334
    assert result.objective_value == 334


@pytest.mark.parametrize(
    ("optimization_request", "message"),
    [
        (
            OptimizationRequest((_resource("same"), _resource("same")), (), (), 30),
            "duplicate resource ID: same",
        ),
        (
            OptimizationRequest((), (_demand("same"), _demand("same")), (), 30),
            "duplicate destination ID: same",
        ),
        (
            OptimizationRequest(
                (_resource("engine"),),
                (_demand("site"),),
                (
                    _candidate("engine", "site", 1),
                    _candidate("engine", "site", 2),
                ),
                30,
            ),
            "duplicate route pair: engine -> site",
        ),
        (
            OptimizationRequest(
                (_resource("engine"),),
                (_demand("site"),),
                (_candidate("missing", "site", 1),),
                30,
            ),
            "unknown resource ID: missing",
        ),
        (
            OptimizationRequest(
                (_resource("engine"),),
                (_demand("site"),),
                (_candidate("engine", "missing", 1),),
                30,
            ),
            "unknown destination ID: missing",
        ),
    ],
)
def test_request_rejects_duplicate_and_unknown_identifiers(
    optimization_request: OptimizationRequest,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        solve_allocation(optimization_request)


@pytest.mark.parametrize("travel_minutes", (nan, inf, -0.01))
def test_request_rejects_nonfinite_or_negative_route_time(
    travel_minutes: float,
) -> None:
    request = OptimizationRequest(
        (_resource("engine"),),
        (_demand("site"),),
        (_candidate("engine", "site", travel_minutes),),
        30,
    )

    with pytest.raises(ValueError, match="travel_minutes.*finite and nonnegative"):
        solve_allocation(request)


@pytest.mark.parametrize("risk", (nan, inf, 100.01))
def test_request_rejects_risk_outside_normalized_range(risk: float) -> None:
    request = OptimizationRequest((), (_demand("site", risk=risk),), (), 30)

    with pytest.raises(ValueError, match="weighted_risk.*between 0 and 100"):
        solve_allocation(request)


def test_explanation_is_deterministic_json_and_names_every_constraint_type() -> None:
    demand = _demand("community", capacity=2, risk=75)
    request = OptimizationRequest(
        resources=(
            _resource("unavailable", available=False),
            _resource("incompatible", capabilities=frozenset({"crew"})),
            _resource("unreachable"),
            _resource("slow"),
            _resource("small"),
        ),
        demands=(demand,),
        routes=(
            _candidate("unavailable", "community", 5),
            _candidate("incompatible", "community", 5),
            _candidate("unreachable", "community", 0, RouteStatus.UNREACHABLE),
            _candidate("slow", "community", 31),
            _candidate("small", "community", 5),
        ),
        max_response_minutes=30,
    )

    result = solve_allocation(request)
    explanation = explain_result(result)

    assert explanation == explain_result(result)
    json.dumps(explanation, sort_keys=True, allow_nan=False)
    assert explanation["status"] == "OPTIMAL"
    assert explanation["algorithm_version"] == "allocation-v1"
    assert explanation["selected_assignments"] == []
    assert explanation["uncovered_destinations"] == [
        {
            "destination_id": "community",
            "limiting_reason": "; ".join(result.binding_constraints),
        }
    ]
    assert explanation["unassigned_resource_ids"] == [
        "incompatible",
        "slow",
        "small",
        "unavailable",
        "unreachable",
    ]
    assert {
        constraint.split(":", 1)[0] for constraint in result.binding_constraints
    } == {
        "availability",
        "capacity",
        "compatibility",
        "response-time",
        "route",
    }
    assert explanation["objective_components"] == {
        "travel_cost": 0,
        "uncovered_risk_penalty": 750,
        "objective_value": 750,
    }


def test_explanation_describes_assignment_travel_and_capacity() -> None:
    result = solve_allocation(_example_request())

    explanation = explain_result(result)

    assert explanation["selected_assignments"] == [
        {
            "resource_id": "engine-close",
            "destination_id": "high-risk",
            "travel_minutes": 5,
            "capacity": 1,
            "rationale": (
                "engine-close supplies capacity 1 to high-risk with 5-minute travel."
            ),
        }
    ]


def test_explanation_stably_sorts_every_collection() -> None:
    result = OptimizationResult(
        "OPTIMAL",
        (
            Assignment("zulu", "bravo", 2, 1),
            Assignment("alpha", "alpha", 1, 1),
        ),
        ("bravo", "alpha"),
        3,
        0,
        3,
        1,
        "allocation-v1",
        ("zulu", "alpha"),
        (
            "route: destination=bravo; route is unreachable",
            "capacity: destination=alpha; capacity was not allocated",
        ),
    )

    explanation = explain_result(result)

    assert [
        assignment["resource_id"]
        for assignment in explanation["selected_assignments"]  # type: ignore[union-attr]
    ] == ["alpha", "zulu"]
    assert [
        destination["destination_id"]
        for destination in explanation["uncovered_destinations"]  # type: ignore[union-attr]
    ] == ["alpha", "bravo"]
    assert explanation["unassigned_resource_ids"] == ["alpha", "zulu"]
    assert explanation["binding_constraints"] == sorted(result.binding_constraints)


def test_result_positional_constructor_keeps_defaulted_explanation_fields() -> None:
    result = OptimizationResult("UNKNOWN", (), (), 0, 0, 0, 0, "allocation-v1")

    assert result.unassigned_resource_ids == ()
    assert result.binding_constraints == ()


def test_input_order_does_not_change_the_deterministic_solution() -> None:
    request = _example_request()

    forward = solve_allocation(request)
    reversed_result = solve_allocation(
        replace(
            request,
            resources=tuple(reversed(request.resources)),
            demands=tuple(reversed(request.demands)),
            routes=tuple(reversed(request.routes)),
        )
    )

    assert replace(forward, runtime_milliseconds=0) == replace(
        reversed_result,
        runtime_milliseconds=0,
    )
