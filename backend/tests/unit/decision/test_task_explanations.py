import json
from math import nan

import pytest

from wildfireops.decision.task_explanations import (
    explain_task_plan,
    serialize_task_explanation,
)


def test_explanation_reports_wind_spot_fire_and_closed_route() -> None:
    previous = {
        "objective": "fastest-response",
        "wind": {"speedMps": 6.7, "directionDegrees": 160},
        "closedEdgeIds": [],
        "tasks": [{"taskId": "park-evac", "incidentId": "park-fire", "penalty": 200}],
        "assignments": [{"resourceId": "bus-1", "taskId": "park-evac"}],
    }
    current = {
        "objective": "protect-critical-services",
        "wind": {"speedMps": 9.0, "directionDegrees": 45},
        "closedEdgeIds": ["edge-32"],
        "tasks": [
            {"taskId": "park-evac", "incidentId": "park-fire", "penalty": 200},
            {"taskId": "spot-comms", "incidentId": "spot-fire", "penalty": 900},
        ],
        "assignments": [{"resourceId": "bus-1", "taskId": "spot-comms"}],
    }

    explanation = explain_task_plan(previous, current)

    assert [item.code for item in explanation.changes] == [
        "objective.changed",
        "wind.changed",
        "incident.task-added",
        "route.closed",
        "assignment.changed",
    ]


def test_initial_plan_explains_outcome_and_each_uncovered_task() -> None:
    explanation = explain_task_plan(
        None,
        {
            "objective": "fastest-response",
            "status": "OPTIMAL",
            "tasks": [
                {"taskId": "park-comms", "requiredCapacity": 2},
                {"taskId": "spot-substation", "requiredCapacity": 2},
            ],
            "assignments": [
                {"resourceId": "engine-1", "taskId": "spot-substation"}
            ],
            "coveredTaskIds": ["spot-substation"],
            "uncoveredTaskIds": ["park-comms"],
            "candidateFacts": [
                {
                    "resourceId": "engine-1",
                    "taskId": "park-comms",
                    "capacity": 2,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 4,
                    "deadlineMinutes": 30,
                    "eligible": True,
                }
            ],
        },
    )

    assert [item.code for item in explanation.changes] == [
        "plan.outcome",
        "task.uncovered-contention",
    ]
    assert explanation.changes[0].summary == (
        "The plan covers 1 of 2 tasks; 1 remains uncovered."
    )
    assert explanation.changes[1].summary == (
        "park-comms remains uncovered because its compatible resource is assigned elsewhere."
    )
    assert explanation.changes[1].evidence["resourceIds"] == ("engine-1",)


def test_unassigned_eligible_capacity_is_an_objective_tradeoff_not_contention() -> None:
    explanation = explain_task_plan(
        None,
        {
            "objective": "fastest-response",
            "algorithm": {"objectiveWeights": {"travelWeight": 3}},
            "status": "OPTIMAL",
            "tasks": [
                {
                    "taskId": "remote-structure",
                    "requiredCapacity": 1,
                    "penalty": 10,
                }
            ],
            "assignments": [],
            "coveredTaskIds": [],
            "uncoveredTaskIds": ["remote-structure"],
            "candidateFacts": [
                {
                    "resourceId": "engine-1",
                    "taskId": "remote-structure",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 12.1,
                    "deadlineMinutes": 30,
                    "eligible": True,
                }
            ],
        },
    )

    reason = explanation.changes[1]
    assert reason.code == "task.uncovered-objective-tradeoff"
    assert reason.summary == (
        "remote-structure remains uncovered because assigning eligible resources "
        "would not improve the selected objective."
    )
    assert reason.evidence == {
        "taskId": "remote-structure",
        "objective": "fastest-response",
        "requiredCapacity": 1,
        "uncoveredPenalty": 10,
        "travelWeight": 3,
        "minimumCoverTravelCost": 39,
        "comparison": "travel-cost-higher",
        "candidateTravelCosts": (
            {
                "resourceId": "engine-1",
                "capacity": 1,
                "travelMinutes": 12.1,
                "weightedTravelCost": 39,
            },
        ),
    }
    assert all(item.code != "task.uncovered-contention" for item in explanation.changes)


def test_objective_tradeoff_reports_a_tie_without_calling_it_more_expensive() -> None:
    explanation = explain_task_plan(
        None,
        {
            "objective": "fastest-response",
            "algorithm": {"objectiveWeights": {"travelWeight": 2}},
            "status": "OPTIMAL",
            "tasks": [
                {"taskId": "equal-cost-task", "requiredCapacity": 1, "penalty": 10}
            ],
            "assignments": [],
            "coveredTaskIds": [],
            "uncoveredTaskIds": ["equal-cost-task"],
            "candidateFacts": [
                {
                    "resourceId": "engine-1",
                    "taskId": "equal-cost-task",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 5,
                    "deadlineMinutes": 30,
                    "eligible": True,
                }
            ],
        },
    )

    reason = explanation.changes[1]
    assert reason.code == "task.uncovered-objective-tradeoff"
    assert reason.evidence["minimumCoverTravelCost"] == 10
    assert reason.evidence["uncoveredPenalty"] == 10
    assert reason.evidence["comparison"] == "equal"
    assert "more expensive" not in reason.summary


def test_feasible_incumbent_does_not_claim_an_objective_tradeoff() -> None:
    explanation = explain_task_plan(
        None,
        {
            "objective": "fastest-response",
            "algorithm": {"objectiveWeights": {"travelWeight": 1}},
            "status": "FEASIBLE",
            "tasks": [
                {"taskId": "task-a", "requiredCapacity": 1, "penalty": 50},
                {"taskId": "task-b", "requiredCapacity": 1, "penalty": 200},
            ],
            "assignments": [{"resourceId": "r1", "taskId": "task-b"}],
            "coveredTaskIds": ["task-b"],
            "uncoveredTaskIds": ["task-a"],
            "candidateFacts": [
                {
                    "resourceId": "r1",
                    "taskId": "task-a",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 1,
                    "deadlineMinutes": 120,
                    "eligible": True,
                },
                {
                    "resourceId": "r2",
                    "taskId": "task-a",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 80,
                    "deadlineMinutes": 120,
                    "eligible": True,
                },
                {
                    "resourceId": "r1",
                    "taskId": "task-b",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 100,
                    "deadlineMinutes": 120,
                    "eligible": True,
                },
                {
                    "resourceId": "r2",
                    "taskId": "task-b",
                    "capacity": 1,
                    "available": True,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 1,
                    "deadlineMinutes": 120,
                    "eligible": True,
                },
            ],
        },
    )

    reason = explanation.changes[1]
    assert reason.code == "task.uncovered-feasible-incumbent"
    assert reason.summary == (
        "task-a remains uncovered in the feasible incumbent; optimality is not proven."
    )
    assert reason.evidence == {
        "taskId": "task-a",
        "status": "FEASIBLE",
        "optimalityProven": False,
        "requiredCapacity": 1,
        "unassignedEligibleCapacity": 1,
        "resourceIds": ("r2",),
    }
    assert "objective" not in reason.summary
    assert all(
        item.code != "task.uncovered-objective-tradeoff"
        for item in explanation.changes
    )


def test_uncovered_reason_uses_candidate_evidence_not_scores() -> None:
    explanation = explain_task_plan(
        None,
        {
            "status": "OPTIMAL",
            "tasks": [{"taskId": "hospital", "requiredCapacity": 4}],
            "coveredTaskIds": [],
            "uncoveredTaskIds": ["hospital"],
            "candidateFacts": [
                {
                    "resourceId": "team-1",
                    "taskId": "hospital",
                    "available": False,
                    "capabilityCompatible": True,
                    "routeReachable": True,
                    "travelMinutes": 5,
                    "deadlineMinutes": 30,
                    "eligible": False,
                }
            ],
        },
    )

    reason = explanation.changes[1]
    assert reason.code == "task.uncovered-availability"
    assert reason.summary == (
        "hospital remains uncovered because its compatible resource is unavailable."
    )
    assert "penalty" not in reason.evidence


def test_task_added_and_removed_are_distinct() -> None:
    explanation = explain_task_plan(
        {"tasks": [{"taskId": "park", "incidentId": "park-fire"}]},
        {"tasks": [{"taskId": "spot", "incidentId": "spot-fire"}]},
    )

    assert [(item.code, item.evidence["taskId"]) for item in explanation.changes] == [
        ("incident.task-added", "spot"),
        ("incident.task-removed", "park"),
    ]


def test_priority_change_records_before_and_after_penalty() -> None:
    explanation = explain_task_plan(
        {"tasks": [{"taskId": "hospital", "penalty": 300}]},
        {"tasks": [{"taskId": "hospital", "penalty": 900}]},
    )

    assert explanation.changes[0].evidence == {
        "taskId": "hospital",
        "before": 300,
        "after": 900,
    }


def test_route_reopened_names_the_exact_edge() -> None:
    explanation = explain_task_plan(
        {"closedEdgeIds": ["edge-32"]}, {"closedEdgeIds": []}
    )

    assert explanation.changes[0].evidence == {"edgeId": "edge-32"}


def test_resource_unavailable_names_the_resource() -> None:
    explanation = explain_task_plan(
        {"resources": [{"resourceId": "bus-1", "available": True}]},
        {"resources": [{"resourceId": "bus-1", "available": False}]},
    )

    assert explanation.changes[0].evidence == {"resourceId": "bus-1"}


def test_assignment_change_names_old_and_new_task() -> None:
    explanation = explain_task_plan(
        {"assignments": [{"resourceId": "bus-1", "taskId": "park-evac"}]},
        {"assignments": [{"resourceId": "bus-1", "taskId": "spot-comms"}]},
    )

    assert explanation.changes[0].evidence == {
        "resourceId": "bus-1",
        "beforeTaskId": "park-evac",
        "afterTaskId": "spot-comms",
    }


def test_reordered_json_inputs_produce_same_explanation() -> None:
    previous = {
        "closedEdgeIds": ["edge-old-a", "edge-old-b"],
        "tasks": [
            {"taskId": "park", "incidentId": "park-fire"},
            {"taskId": "hospital", "penalty": 300},
        ],
        "resources": [
            {"resourceId": "bus-1", "available": True},
            {"resourceId": "engine-1", "available": True},
        ],
        "assignments": [
            {"resourceId": "bus-1", "taskId": "park"},
            {"resourceId": "engine-1", "taskId": "hospital"},
        ],
    }
    current = {
        "closedEdgeIds": ["edge-new-a", "edge-new-b"],
        "tasks": [
            {"taskId": "spot", "incidentId": "spot-fire"},
            {"taskId": "hospital", "penalty": 900},
        ],
        "resources": [
            {"resourceId": "bus-1", "available": False},
            {"resourceId": "engine-1", "available": True},
        ],
        "assignments": [
            {"resourceId": "bus-1", "taskId": "spot"},
            {"resourceId": "engine-1", "taskId": "hospital"},
        ],
    }

    assert explain_task_plan(previous, current) == explain_task_plan(
        {
            **previous,
            "closedEdgeIds": list(reversed(previous["closedEdgeIds"])),
            "tasks": list(reversed(previous["tasks"])),
            "resources": list(reversed(previous["resources"])),
            "assignments": list(reversed(previous["assignments"])),
        },
        {
            **current,
            "closedEdgeIds": list(reversed(current["closedEdgeIds"])),
            "tasks": list(reversed(current["tasks"])),
            "resources": list(reversed(current["resources"])),
            "assignments": list(reversed(current["assignments"])),
        },
    )


def test_serializer_is_json_compatible() -> None:
    value = explain_task_plan(
        {"wind": {"speedMps": 6.7}},
        {"wind": {"speedMps": 9.0}},
    )

    json.dumps(serialize_task_explanation(value), allow_nan=False)


def test_rejects_duplicate_row_keys() -> None:
    with pytest.raises(ValueError, match="duplicate tasks.taskId: park"):
        explain_task_plan(
            {"tasks": []},
            {"tasks": [{"taskId": "park"}, {"taskId": "park"}]},
        )


def test_rejects_non_json_evidence() -> None:
    with pytest.raises(ValueError, match="unsupported JSON value"):
        explain_task_plan({"wind": {"speedMps": nan}}, {"wind": {}})


def test_every_change_has_exact_summary_and_evidence() -> None:
    explanation = explain_task_plan(
        {
            "objective": "fastest-response",
            "wind": {"speedMps": 6.7},
            "closedEdgeIds": ["edge-reopened"],
            "tasks": [
                {"taskId": "removed", "incidentId": "park-fire"},
                {"taskId": "hospital", "penalty": 300},
            ],
            "resources": [{"resourceId": "bus-1", "available": True}],
            "assignments": [{"resourceId": "bus-1", "taskId": "removed"}],
        },
        {
            "objective": "protect-critical-services",
            "wind": {"speedMps": 9.0},
            "closedEdgeIds": ["edge-closed"],
            "tasks": [
                {"taskId": "added", "incidentId": "spot-fire"},
                {"taskId": "hospital", "penalty": 900},
            ],
            "resources": [{"resourceId": "bus-1", "available": False}],
            "assignments": [{"resourceId": "bus-1", "taskId": "added"}],
        },
    )

    assert [
        (item.code, item.summary, item.evidence) for item in explanation.changes
    ] == [
        (
            "objective.changed",
            "The planning objective changed.",
            {"before": "fastest-response", "after": "protect-critical-services"},
        ),
        (
            "wind.changed",
            "Wind conditions changed.",
            {"before": {"speedMps": 6.7}, "after": {"speedMps": 9.0}},
        ),
        (
            "incident.task-added",
            "A new incident task was added.",
            {"taskId": "added", "incidentId": "spot-fire"},
        ),
        (
            "incident.task-removed",
            "An incident task was removed.",
            {"taskId": "removed", "incidentId": "park-fire"},
        ),
        (
            "task.priority-changed",
            "A task priority changed.",
            {"taskId": "hospital", "before": 300, "after": 900},
        ),
        ("route.closed", "A corridor closed.", {"edgeId": "edge-closed"}),
        ("route.reopened", "A corridor reopened.", {"edgeId": "edge-reopened"}),
        (
            "resource.unavailable",
            "A resource became unavailable.",
            {"resourceId": "bus-1"},
        ),
        (
            "assignment.changed",
            "A resource assignment changed.",
            {
                "resourceId": "bus-1",
                "beforeTaskId": "removed",
                "afterTaskId": "added",
            },
        ),
    ]


@pytest.mark.parametrize(
    "assignment",
    [
        {"resourceId": "bus-1"},
        {"resourceId": "bus-1", "taskId": ""},
        {"resourceId": "bus-1", "taskId": " "},
        {"resourceId": "bus-1", "taskId": []},
    ],
)
def test_rejects_malformed_assignment_task_id(assignment: object) -> None:
    with pytest.raises(
        ValueError,
        match="assignments.taskId must be a nonblank string",
    ):
        explain_task_plan({"assignments": [assignment]}, {"assignments": []})


@pytest.mark.parametrize(
    ("closed_edge_ids", "message"),
    [
        ([""], "closedEdgeIds entries must be nonblank strings"),
        ([" "], "closedEdgeIds entries must be nonblank strings"),
        (["edge-32", "edge-32"], "duplicate closedEdgeIds entry: edge-32"),
    ],
)
def test_rejects_invalid_closed_edge_ids(
    closed_edge_ids: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        explain_task_plan({"closedEdgeIds": []}, {"closedEdgeIds": closed_edge_ids})
