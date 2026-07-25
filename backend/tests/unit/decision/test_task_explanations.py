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


def test_initial_plan_has_no_change_claims() -> None:
    assert explain_task_plan(None, {"objective": "fastest-response"}).changes == ()


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
        "tasks": [
            {"taskId": "park", "incidentId": "park-fire"},
            {"taskId": "hospital", "penalty": 300},
        ],
        "assignments": [
            {"resourceId": "bus-1", "taskId": "park"},
            {"resourceId": "engine-1", "taskId": "hospital"},
        ],
    }
    current = {
        "tasks": [
            {"taskId": "spot", "incidentId": "spot-fire"},
            {"taskId": "hospital", "penalty": 900},
        ],
        "assignments": [
            {"resourceId": "bus-1", "taskId": "spot"},
            {"resourceId": "engine-1", "taskId": "hospital"},
        ],
    }

    assert explain_task_plan(previous, current) == explain_task_plan(
        {
            **previous,
            "tasks": list(reversed(previous["tasks"])),
            "assignments": list(reversed(previous["assignments"])),
        },
        {
            **current,
            "tasks": list(reversed(current["tasks"])),
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
