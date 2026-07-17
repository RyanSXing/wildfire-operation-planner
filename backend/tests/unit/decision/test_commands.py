from dataclasses import replace
from hashlib import sha256
from math import inf, nan
from typing import cast
from uuid import UUID

import pytest

from wildfireops.decision.commands import (
    DecisionRecommendation,
    DecisionRequest,
    DecisionValidationError,
    _normalize_request,
    _validate_decision,
)


@pytest.mark.parametrize(
    "edited_assignments",
    (("resource-only",), ("resource", "destination", "extra")),
)
def test_malformed_edited_assignments_raise_decision_validation_error(
    edited_assignments: tuple[str, ...],
) -> None:
    request = DecisionRequest(
        "edit",
        "Reassign",
        cast(tuple[tuple[str, str], ...], (edited_assignments,)),
    )

    with pytest.raises(
        DecisionValidationError,
        match="edited_assignments must contain resource and destination pairs",
    ):
        _normalize_request(request)


def _recommendation() -> DecisionRecommendation:
    closure_hash = sha256(b"[]").hexdigest()
    return DecisionRecommendation(
        id=UUID(int=1),
        scenario_version_id=UUID(int=2),
        incident_snapshot_id=UUID(int=3),
        input_version="a" * 64,
        source_versions={},
        graph_version="graph-v1",
        risk_version="risk-v1",
        algorithm_version="allocation-v1",
        solver_status="OPTIMAL",
        request_inputs={
            "resources": [
                {
                    "resource_id": "engine-1",
                    "available": True,
                    "capabilities": ["water"],
                    "capacity": 2,
                }
            ],
            "demands": [
                {
                    "destination_id": "town-1",
                    "required_capability": "water",
                    "required_capacity": 2,
                }
            ],
            "candidate_routes": [
                {
                    "resource_id": "engine-1",
                    "destination_id": "town-1",
                    "route": {
                        "status": "reachable",
                        "edge_ids": ["edge-1"],
                        "distance_meters": 1_000.0,
                        "travel_minutes": 5.0,
                        "graph_version": "graph-v1",
                        "closure_hash": closure_hash,
                    },
                }
            ],
            "limits": {"max_response_minutes": 30},
            "overlays": {"closed_edge_ids": []},
        },
        proposals=(),
        terminal_decision_id=None,
    )


@pytest.mark.parametrize("travel_minutes", (nan, inf, -0.01))
def test_edit_rejects_nonfinite_or_negative_persisted_route_travel(
    travel_minutes: float,
) -> None:
    recommendation = _recommendation()
    inputs = dict(recommendation.request_inputs)
    routes = cast(list[dict[str, object]], inputs["candidate_routes"])
    inputs["candidate_routes"] = [
        {
            **routes[0],
            "route": {
                **cast(dict[str, object], routes[0]["route"]),
                "travel_minutes": travel_minutes,
            },
        }
    ]

    with pytest.raises(
        DecisionValidationError,
        match="route travel_minutes must be finite and nonnegative",
    ):
        _validate_decision(
            replace(recommendation, request_inputs=inputs),
            DecisionRequest("edit", "Reassign", (("engine-1", "town-1"),)),
        )


def test_edit_rejects_persisted_route_from_another_graph() -> None:
    recommendation = _recommendation()
    inputs = dict(recommendation.request_inputs)
    routes = cast(list[dict[str, object]], inputs["candidate_routes"])
    inputs["candidate_routes"] = [
        {
            **routes[0],
            "route": {
                **cast(dict[str, object], routes[0]["route"]),
                "graph_version": "graph-v2",
            },
        }
    ]

    with pytest.raises(DecisionValidationError, match="graph version"):
        _validate_decision(
            replace(recommendation, request_inputs=inputs),
            DecisionRequest("edit", "Reassign", (("engine-1", "town-1"),)),
        )
