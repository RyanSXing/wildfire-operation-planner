"""Deterministic, evidence-backed task-plan change explanations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from math import ceil, isfinite

from wildfireops.domain.observations import (
    FrozenJsonObject,
    FrozenJsonValue,
    freeze_json_object,
)


_ORDER = {
    "plan.outcome": 0,
    "objective.changed": 10,
    "wind.changed": 20,
    "incident.task-added": 30,
    "incident.task-removed": 40,
    "task.priority-changed": 50,
    "route.closed": 60,
    "route.reopened": 70,
    "resource.unavailable": 80,
    "assignment.changed": 90,
    "task.uncovered-solver-status": 100,
    "task.uncovered-availability": 101,
    "task.uncovered-compatibility": 102,
    "task.uncovered-route": 103,
    "task.uncovered-deadline": 104,
    "task.uncovered-capacity": 105,
    "task.uncovered-contention": 106,
    "task.uncovered-feasible-incumbent": 107,
    "task.uncovered-objective-tradeoff": 108,
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
    changes = _outcome_changes(current_input)
    if previous is None:
        _validate_collections(current_input)
        return TaskPlanExplanation(tuple(changes))
    previous_input = _planning_input(previous, "previous")
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


def _outcome_changes(current: FrozenJsonObject) -> list[PlanChange]:
    status = current.get("status")
    covered = current.get("coveredTaskIds")
    uncovered = current.get("uncoveredTaskIds")
    if not isinstance(status, str) or covered is None or uncovered is None:
        return []
    covered_ids = _strings(covered, "coveredTaskIds")
    uncovered_ids = _strings(uncovered, "uncoveredTaskIds")
    total = len(covered_ids) + len(uncovered_ids)
    remaining = len(uncovered_ids)
    noun = "task" if total == 1 else "tasks"
    remainder = "none remain uncovered" if remaining == 0 else (
        f"{remaining} remains uncovered" if remaining == 1 else f"{remaining} remain uncovered"
    )
    changes = [
        _change(
            "plan.outcome",
            f"The plan covers {len(covered_ids)} of {total} {noun}; {remainder}.",
            {
                "status": status,
                "coveredTaskIds": covered_ids,
                "uncoveredTaskIds": uncovered_ids,
            },
        )
    ]
    tasks = _rows(current.get("tasks"), "tasks", "taskId")
    assignments = _rows(
        current.get("assignments"), "assignments", "resourceId", "taskId"
    )
    facts = _candidate_facts(current.get("candidateFacts"))
    changes.extend(
        _uncovered_reason(
            task_id,
            status,
            tasks.get(task_id),
            assignments,
            facts,
            current,
        )
        for task_id in uncovered_ids
    )
    return changes


def _uncovered_reason(
    task_id: str,
    status: str,
    task: FrozenJsonObject | None,
    assignments: Mapping[str, FrozenJsonObject],
    facts: tuple[FrozenJsonObject, ...],
    planning: FrozenJsonObject,
) -> PlanChange:
    task_facts = tuple(item for item in facts if item.get("taskId") == task_id)
    if status not in {"FEASIBLE", "OPTIMAL"}:
        return _change(
            "task.uncovered-solver-status",
            f"{task_id} remains uncovered because the solver returned {status.lower()}.",
            {"taskId": task_id, "status": status},
        )
    compatible = tuple(
        item for item in task_facts if item.get("capabilityCompatible") is True
    )
    available = tuple(item for item in compatible if item.get("available") is True)
    reachable = tuple(item for item in available if item.get("routeReachable") is True)
    eligible = tuple(item for item in reachable if item.get("eligible") is True)
    if compatible and not available:
        return _candidate_reason(
            "task.uncovered-availability",
            task_id,
            compatible,
            "because its compatible resource is unavailable",
        )
    if not compatible:
        return _candidate_reason(
            "task.uncovered-compatibility",
            task_id,
            task_facts,
            "because no resource has the required capability",
        )
    if available and not reachable:
        return _candidate_reason(
            "task.uncovered-route",
            task_id,
            available,
            "because no compatible route is reachable",
        )
    if reachable and not eligible:
        return _candidate_reason(
            "task.uncovered-deadline",
            task_id,
            reachable,
            "because compatible routes miss its deadline",
        )
    required = None if task is None else task.get("requiredCapacity")
    capacity = 0
    for item in eligible:
        value = item.get("capacity")
        if isinstance(value, int) and not isinstance(value, bool):
            capacity += value
    if isinstance(required, int) and not isinstance(required, bool) and capacity < required:
        return _candidate_reason(
            "task.uncovered-capacity",
            task_id,
            eligible,
            "because eligible resources cannot supply its required capacity",
            {"requiredCapacity": required, "eligibleCapacity": capacity},
        )
    unassigned = tuple(
        item for item in eligible if item.get("resourceId") not in assignments
    )
    unassigned_capacity = sum(
        value
        for item in unassigned
        if isinstance((value := item.get("capacity")), int)
        and not isinstance(value, bool)
    )
    if (
        isinstance(required, int)
        and not isinstance(required, bool)
        and unassigned_capacity >= required
    ):
        if status == "FEASIBLE":
            return _change(
                "task.uncovered-feasible-incumbent",
                f"{task_id} remains uncovered in the feasible incumbent; "
                "optimality is not proven.",
                {
                    "taskId": task_id,
                    "status": status,
                    "optimalityProven": False,
                    "requiredCapacity": required,
                    "unassignedEligibleCapacity": unassigned_capacity,
                    "resourceIds": tuple(
                        sorted(str(item.get("resourceId")) for item in unassigned)
                    ),
                },
            )
        return _objective_tradeoff_reason(task_id, task, unassigned, planning)
    assigned_ids = {
        str(item.get("resourceId"))
        for item in eligible
        if item.get("resourceId") in assignments
    }
    resource_ids = assigned_ids or {
        str(item.get("resourceId")) for item in eligible if item.get("resourceId")
    }
    wording = (
        "its compatible resource is assigned elsewhere"
        if len(resource_ids) == 1
        else "its compatible resources are assigned elsewhere"
    )
    return _change(
        "task.uncovered-contention",
        f"{task_id} remains uncovered because {wording}.",
        {"taskId": task_id, "resourceIds": tuple(sorted(resource_ids))},
    )


def _objective_tradeoff_reason(
    task_id: str,
    task: FrozenJsonObject | None,
    candidates: tuple[FrozenJsonObject, ...],
    planning: FrozenJsonObject,
) -> PlanChange:
    algorithm = planning.get("algorithm")
    weights = algorithm.get("objectiveWeights") if isinstance(algorithm, Mapping) else None
    travel_weight = weights.get("travelWeight") if isinstance(weights, Mapping) else None
    required = None if task is None else task.get("requiredCapacity")
    penalty = None if task is None else task.get("penalty")
    candidate_costs: list[dict[str, object]] = []
    capacity_costs: list[tuple[int, int]] = []
    for item in sorted(candidates, key=lambda value: str(value.get("resourceId"))):
        capacity = item.get("capacity")
        travel_minutes = item.get("travelMinutes")
        weighted_cost = (
            travel_weight * ceil(travel_minutes)
            if isinstance(travel_weight, int)
            and not isinstance(travel_weight, bool)
            and isinstance(travel_minutes, int | float)
            and not isinstance(travel_minutes, bool)
            and isfinite(travel_minutes)
            else None
        )
        row: dict[str, object] = {
            "resourceId": item.get("resourceId"),
            "capacity": capacity,
            "travelMinutes": travel_minutes,
        }
        if weighted_cost is not None:
            row["weightedTravelCost"] = weighted_cost
        candidate_costs.append(row)
        if (
            isinstance(capacity, int)
            and not isinstance(capacity, bool)
            and weighted_cost is not None
        ):
            capacity_costs.append((capacity, weighted_cost))
    minimum_cost = (
        _minimum_cover_cost(required, capacity_costs)
        if isinstance(required, int) and not isinstance(required, bool)
        else None
    )
    comparison = (
        "travel-cost-higher"
        if isinstance(penalty, int)
        and not isinstance(penalty, bool)
        and minimum_cost is not None
        and minimum_cost > penalty
        else (
            "equal"
            if isinstance(penalty, int)
            and not isinstance(penalty, bool)
            and minimum_cost == penalty
            else "travel-cost-lower"
        )
    )
    evidence: dict[str, object] = {
        "taskId": task_id,
        "objective": planning.get("objective"),
        "requiredCapacity": required,
        "uncoveredPenalty": penalty,
        "travelWeight": travel_weight,
        "candidateTravelCosts": candidate_costs,
    }
    if minimum_cost is not None:
        evidence["minimumCoverTravelCost"] = minimum_cost
        evidence["comparison"] = comparison
    summary = (
        f"{task_id} remains uncovered because assigning eligible resources "
        "would not improve the selected objective."
        if comparison != "travel-cost-lower"
        else (
            f"{task_id} remains uncovered despite unassigned eligible resources "
            "that would improve the selected objective."
        )
    )
    return _change("task.uncovered-objective-tradeoff", summary, evidence)


def _minimum_cover_cost(
    required_capacity: int,
    candidates: Sequence[tuple[int, int]],
) -> int | None:
    costs = {0: 0}
    for capacity, cost in candidates:
        updated = dict(costs)
        for supplied, current_cost in costs.items():
            new_supplied = min(required_capacity, supplied + capacity)
            new_cost = current_cost + cost
            if new_cost < updated.get(new_supplied, new_cost + 1):
                updated[new_supplied] = new_cost
        costs = updated
    return costs.get(required_capacity)


def _candidate_reason(
    code: str,
    task_id: str,
    facts: Sequence[FrozenJsonObject],
    reason: str,
    extra: Mapping[str, object] | None = None,
) -> PlanChange:
    resource_ids = tuple(
        sorted(
            str(item.get("resourceId"))
            for item in facts
            if item.get("resourceId") is not None
        )
    )
    return _change(
        code,
        f"{task_id} remains uncovered {reason}.",
        {"taskId": task_id, "resourceIds": resource_ids, **(extra or {})},
    )


def _candidate_facts(value: object) -> tuple[FrozenJsonObject, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueError("candidateFacts must be a sequence")
    return tuple(
        freeze_json_object(item)
        for item in value
        if isinstance(item, Mapping)
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
