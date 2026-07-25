"""Deterministic, evidence-backed task-plan change explanations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json

from wildfireops.domain.observations import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_object,
)


_ORDER = {
    "objective.changed": 10,
    "wind.changed": 20,
    "incident.task-added": 30,
    "incident.task-removed": 40,
    "task.priority-changed": 50,
    "route.closed": 60,
    "route.reopened": 70,
    "resource.unavailable": 80,
    "assignment.changed": 90,
}


@dataclass(frozen=True, slots=True)
class PlanChange:
    code: str
    summary: str
    evidence: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class TaskPlanExplanation:
    changes: tuple[PlanChange, ...]


def explain_task_plan(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> TaskPlanExplanation:
    """Report only explicit differences between canonical planning inputs."""
    current_input = _planning_input(current, "current")
    if previous is None:
        _validate_collections(current_input)
        return TaskPlanExplanation(())
    previous_input = _planning_input(previous, "previous")
    changes: list[PlanChange] = []
    if previous_input.get("objective") != current_input.get("objective"):
        changes.append(
            _change(
                "objective.changed",
                "The planning objective changed.",
                {
                    "before": previous_input.get("objective"),
                    "after": current_input.get("objective"),
                },
            )
        )
    if previous_input.get("wind") != current_input.get("wind"):
        changes.append(
            _change(
                "wind.changed",
                "Wind conditions changed.",
                {
                    "before": previous_input.get("wind"),
                    "after": current_input.get("wind"),
                },
            )
        )
    changes.extend(_task_changes(previous_input, current_input))
    changes.extend(_road_changes(previous_input, current_input))
    changes.extend(_assignment_changes(previous_input, current_input))
    return TaskPlanExplanation(
        tuple(sorted(changes, key=lambda item: (_ORDER[item.code], _sort_key(item))))
    )


def serialize_task_explanation(
    explanation: TaskPlanExplanation,
) -> dict[str, object]:
    return {
        "changes": [
            {
                "code": item.code,
                "summary": item.summary,
                "evidence": _json_value(item.evidence),
            }
            for item in explanation.changes
        ]
    }


def _task_changes(
    previous: FrozenJsonObject,
    current: FrozenJsonObject,
) -> list[PlanChange]:
    before = _rows(previous.get("tasks"), "tasks", "taskId")
    after = _rows(current.get("tasks"), "tasks", "taskId")
    changes = [
        _change(
            "incident.task-added",
            "A new incident task was added.",
            {"taskId": task_id, "incidentId": after[task_id].get("incidentId")},
        )
        for task_id in sorted(after.keys() - before.keys())
    ]
    changes.extend(
        _change(
            "incident.task-removed",
            "An incident task was removed.",
            {"taskId": task_id, "incidentId": before[task_id].get("incidentId")},
        )
        for task_id in sorted(before.keys() - after.keys())
    )
    for task_id in sorted(before.keys() & after.keys()):
        old_penalty = before[task_id].get("penalty")
        new_penalty = after[task_id].get("penalty")
        if old_penalty != new_penalty:
            changes.append(
                _change(
                    "task.priority-changed",
                    "A task priority changed.",
                    {"taskId": task_id, "before": old_penalty, "after": new_penalty},
                )
            )
    old_resources = _rows(previous.get("resources"), "resources", "resourceId")
    new_resources = _rows(current.get("resources"), "resources", "resourceId")
    changes.extend(
        _change(
            "resource.unavailable",
            "A resource became unavailable.",
            {"resourceId": resource_id},
        )
        for resource_id in sorted(old_resources.keys() & new_resources.keys())
        if old_resources[resource_id].get("available") is True
        and new_resources[resource_id].get("available") is False
    )
    return changes


def _road_changes(
    previous: FrozenJsonObject,
    current: FrozenJsonObject,
) -> list[PlanChange]:
    before = set(_strings(previous.get("closedEdgeIds"), "closedEdgeIds"))
    after = set(_strings(current.get("closedEdgeIds"), "closedEdgeIds"))
    return [
        *(
            _change("route.closed", "A corridor closed.", {"edgeId": edge_id})
            for edge_id in sorted(after - before)
        ),
        *(
            _change("route.reopened", "A corridor reopened.", {"edgeId": edge_id})
            for edge_id in sorted(before - after)
        ),
    ]


def _assignment_changes(
    previous: FrozenJsonObject,
    current: FrozenJsonObject,
) -> list[PlanChange]:
    before = _rows(previous.get("assignments"), "assignments", "resourceId", "taskId")
    after = _rows(current.get("assignments"), "assignments", "resourceId", "taskId")
    return [
        _change(
            "assignment.changed",
            "A resource assignment changed.",
            {
                "resourceId": resource_id,
                "beforeTaskId": before.get(resource_id, {}).get("taskId"),
                "afterTaskId": after.get(resource_id, {}).get("taskId"),
            },
        )
        for resource_id in sorted(before.keys() | after.keys())
        if before.get(resource_id, {}).get("taskId")
        != after.get(resource_id, {}).get("taskId")
    ]


def _planning_input(value: object, field: str) -> FrozenJsonObject:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return freeze_json_object(value)


def _validate_collections(value: FrozenJsonObject) -> None:
    _rows(value.get("tasks"), "tasks", "taskId")
    _rows(value.get("resources"), "resources", "resourceId")
    _rows(value.get("assignments"), "assignments", "resourceId", "taskId")
    _strings(value.get("closedEdgeIds"), "closedEdgeIds")


def _strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{field} must be a sequence")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} entries must be strings")
        if not item.strip():
            raise ValueError(f"{field} entries must be nonblank strings")
        if item in seen:
            raise ValueError(f"duplicate {field} entry: {item}")
        seen.add(item)
        result.append(item)
    return tuple(result)


def _rows(
    value: object,
    field: str,
    key: str,
    required_key: str | None = None,
) -> dict[str, FrozenJsonObject]:
    if value is None:
        return {}
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError(f"{field} must be a sequence")
    result: dict[str, FrozenJsonObject] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} entries must be objects")
        identifier = item.get(key)
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"{field}.{key} must be a nonblank string")
        if identifier in result:
            raise ValueError(f"duplicate {field}.{key}: {identifier}")
        if required_key is not None:
            required_value = item.get(required_key)
            if not isinstance(required_value, str) or not required_value.strip():
                raise ValueError(f"{field}.{required_key} must be a nonblank string")
        result[identifier] = freeze_json_object(item)
    return result


def _change(code: str, summary: str, evidence: Mapping[str, object]) -> PlanChange:
    return PlanChange(code, summary, freeze_json_object(evidence))


def _sort_key(change: PlanChange) -> str:
    return json.dumps(
        _json_value(change.evidence), sort_keys=True, separators=(",", ":")
    )


def _json_value(value: FrozenJsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
