"""Deterministic shared task-plan allocation."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil, isfinite

from ortools.sat.python import cp_model

from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


TASK_ALGORITHM_VERSION = "task-allocation-v1"
_DETERMINISTIC_SEARCH_BUDGET = 1.0
_SOLUTION_STATUSES = frozenset({"OPTIMAL"})
_PUBLIC_STATUSES = frozenset({"INFEASIBLE", "OPTIMAL"})


@dataclass(frozen=True, slots=True)
class TaskDemand:
    task_id: str
    incident_id: str
    asset_id: str
    required_capability: str
    required_capacity: int
    deadline_minutes: int
    uncovered_penalty: int

    def __post_init__(self) -> None:
        for field, value in (
            ("task_id", self.task_id),
            ("incident_id", self.incident_id),
            ("asset_id", self.asset_id),
            ("required_capability", self.required_capability),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be blank")
        if (
            isinstance(self.required_capacity, bool)
            or not isinstance(self.required_capacity, int)
            or self.required_capacity <= 0
        ):
            raise ValueError("required_capacity must be a positive integer")
        if (
            isinstance(self.deadline_minutes, bool)
            or not isinstance(self.deadline_minutes, int)
            or self.deadline_minutes <= 0
        ):
            raise ValueError("deadline_minutes must be a positive integer")
        if (
            isinstance(self.uncovered_penalty, bool)
            or not isinstance(self.uncovered_penalty, int)
            or self.uncovered_penalty < 0
        ):
            raise ValueError("uncovered_penalty must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class TaskCandidateRoute:
    resource_id: str
    task_id: str
    route: RouteResult


@dataclass(frozen=True, slots=True)
class LockedTaskAssignment:
    resource_id: str
    task_id: str


@dataclass(frozen=True, slots=True)
class TaskOptimizationRequest:
    resources: tuple[ResourceUnit, ...]
    tasks: tuple[TaskDemand, ...]
    routes: tuple[TaskCandidateRoute, ...]
    locked_assignments: tuple[LockedTaskAssignment, ...]
    travel_weight: int
    max_solver_seconds: float = 2.0
    algorithm_version: str = TASK_ALGORITHM_VERSION


@dataclass(frozen=True, slots=True)
class TaskAssignment:
    resource_id: str
    task_id: str
    incident_id: str
    asset_id: str
    travel_minutes: float
    capacity: int


@dataclass(frozen=True, slots=True)
class TaskOptimizationResult:
    status: str
    assignments: tuple[TaskAssignment, ...]
    uncovered_task_ids: tuple[str, ...]
    unassigned_resource_ids: tuple[str, ...]
    travel_cost: int
    uncovered_task_penalty: int
    objective_value: int
    binding_constraints: tuple[str, ...]
    runtime_milliseconds: int
    algorithm_version: str


def solve_task_plan(request: TaskOptimizationRequest) -> TaskOptimizationResult:
    resources, tasks, routes, locks = _canonicalize(request)
    resources_by_id = {item.resource_id: item for item in resources}
    tasks_by_id = {item.task_id: item for item in tasks}
    eligible = {
        (route.resource_id, route.task_id): route
        for route in routes
        if _eligible(
            resources_by_id[route.resource_id],
            tasks_by_id[route.task_id],
            route.route,
        )
    }
    _validate_locked_assignments(locks, tasks_by_id, eligible, resources_by_id)
    model = cp_model.CpModel()
    assigned = {
        pair: model.new_bool_var(f"assigned[{pair[0]},{pair[1]}]")
        for pair in eligible
    }
    covered = {
        task.task_id: model.new_bool_var(f"covered[{task.task_id}]")
        for task in tasks
    }
    for resource in resources:
        variables = [
            variable
            for (resource_id, _), variable in assigned.items()
            if resource_id == resource.resource_id
        ]
        if variables:
            model.add(sum(variables) <= 1)
    for task in tasks:
        capacity = [
            (resources_by_id[resource_id].capacity, variable)
            for (resource_id, task_id), variable in assigned.items()
            if task_id == task.task_id
        ]
        if not capacity:
            model.add(covered[task.task_id] == 0)
        else:
            model.add(
                sum(value * variable for value, variable in capacity)
                >= task.required_capacity * covered[task.task_id]
            )
            model.add(
                sum(variable for _, variable in capacity)
                <= len(capacity) * covered[task.task_id]
            )
    for lock in locks:
        model.add(assigned[(lock.resource_id, lock.task_id)] == 1)
    travel_costs = {
        pair: request.travel_weight * ceil(route.route.travel_minutes)
        for pair, route in eligible.items()
    }
    model.minimize(
        sum(travel_costs[pair] * variable for pair, variable in assigned.items())
        + sum(
            task.uncovered_penalty * (1 - covered[task.task_id])
            for task in tasks
        )
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = _DETERMINISTIC_SEARCH_BUDGET
    solver.parameters.max_time_in_seconds = request.max_solver_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    raw_status = solver.status_name(solver.solve(model))
    status = raw_status if raw_status in _PUBLIC_STATUSES else "UNKNOWN"
    selected = (
        tuple(pair for pair, variable in assigned.items() if solver.value(variable))
        if status in _SOLUTION_STATUSES
        else ()
    )
    uncovered = (
        tuple(
            task.task_id
            for task in tasks
            if not solver.value(covered[task.task_id])
        )
        if status in _SOLUTION_STATUSES
        else tuple(task.task_id for task in tasks)
    )
    assignments = tuple(
        TaskAssignment(
            resource_id,
            task_id,
            tasks_by_id[task_id].incident_id,
            tasks_by_id[task_id].asset_id,
            eligible[(resource_id, task_id)].route.travel_minutes,
            resources_by_id[resource_id].capacity,
        )
        for resource_id, task_id in selected
    )
    selected_resources = {item.resource_id for item in assignments}
    travel_cost = sum(travel_costs[pair] for pair in selected)
    uncovered_task_penalty = sum(
        tasks_by_id[task_id].uncovered_penalty for task_id in uncovered
    )
    return TaskOptimizationResult(
        status=status,
        assignments=assignments,
        uncovered_task_ids=uncovered,
        unassigned_resource_ids=tuple(
            item.resource_id
            for item in resources
            if item.resource_id not in selected_resources
        ),
        travel_cost=travel_cost,
        uncovered_task_penalty=uncovered_task_penalty,
        objective_value=travel_cost + uncovered_task_penalty,
        binding_constraints=_binding_constraints(
            status,
            resources,
            tasks,
            routes,
            eligible,
            selected,
            uncovered,
        ),
        runtime_milliseconds=round(solver.wall_time * 1000),
        algorithm_version=request.algorithm_version,
    )


def _canonicalize(
    request: TaskOptimizationRequest,
) -> tuple[
    tuple[ResourceUnit, ...],
    tuple[TaskDemand, ...],
    tuple[TaskCandidateRoute, ...],
    tuple[LockedTaskAssignment, ...],
]:
    if (
        isinstance(request.travel_weight, bool)
        or not isinstance(request.travel_weight, int)
        or request.travel_weight < 0
    ):
        raise ValueError("travel_weight must be a nonnegative integer")
    if (
        isinstance(request.max_solver_seconds, bool)
        or not isinstance(request.max_solver_seconds, int | float)
        or not isfinite(request.max_solver_seconds)
        or request.max_solver_seconds <= 0
    ):
        raise ValueError("max_solver_seconds must be finite and positive")
    resources = tuple(sorted(request.resources, key=lambda item: item.resource_id))
    tasks = tuple(sorted(request.tasks, key=lambda item: item.task_id))
    routes = tuple(
        sorted(request.routes, key=lambda item: (item.resource_id, item.task_id))
    )
    locks = tuple(
        sorted(
            request.locked_assignments,
            key=lambda item: (item.resource_id, item.task_id),
        )
    )
    _reject_duplicates((item.resource_id for item in resources), "resource")
    _reject_duplicates((item.task_id for item in tasks), "task")
    _reject_duplicates(
        ((item.resource_id, item.task_id) for item in routes),
        "route pair",
    )
    _reject_duplicates(
        ((item.resource_id, item.task_id) for item in locks),
        "locked assignment",
    )
    resource_ids = {item.resource_id for item in resources}
    task_ids = {item.task_id for item in tasks}
    for resource in resources:
        if (
            isinstance(resource.capacity, bool)
            or not isinstance(resource.capacity, int)
            or resource.capacity <= 0
        ):
            raise ValueError("resource capacity must be a positive integer")
    for route in routes:
        if route.resource_id not in resource_ids:
            raise ValueError(f"unknown route resource: {route.resource_id}")
        if route.task_id not in task_ids:
            raise ValueError(f"unknown route task: {route.task_id}")
        if route.route.status is RouteStatus.REACHABLE and (
            isinstance(route.route.travel_minutes, bool)
            or not isinstance(route.route.travel_minutes, int | float)
            or not isfinite(route.route.travel_minutes)
            or route.route.travel_minutes < 0
        ):
            raise ValueError("route travel_minutes must be finite and nonnegative")
    for lock in locks:
        if lock.resource_id not in resource_ids or lock.task_id not in task_ids:
            raise ValueError(
                f"unknown locked assignment: {lock.resource_id} -> {lock.task_id}"
            )
    return resources, tasks, routes, locks


def _validate_locked_assignments(
    locks: tuple[LockedTaskAssignment, ...],
    tasks: dict[str, TaskDemand],
    eligible: dict[tuple[str, str], TaskCandidateRoute],
    resources: dict[str, ResourceUnit],
) -> None:
    locked_resources: set[str] = set()
    locked_task_ids: set[str] = set()
    for lock in locks:
        if lock.resource_id in locked_resources:
            raise ValueError(
                f"conflicting locked assignments for resource: {lock.resource_id}"
            )
        locked_resources.add(lock.resource_id)
        if (lock.resource_id, lock.task_id) not in eligible:
            raise ValueError(
                f"locked assignment is not eligible: "
                f"{lock.resource_id} -> {lock.task_id}"
            )
        locked_task_ids.add(lock.task_id)
    for task_id in sorted(locked_task_ids):
        eligible_capacity = sum(
            resources[resource_id].capacity
            for resource_id, candidate_task_id in eligible
            if candidate_task_id == task_id
        )
        if eligible_capacity < tasks[task_id].required_capacity:
            raise ValueError(
                f"locked task has insufficient eligible capacity: {task_id}"
            )


def _eligible(
    resource: ResourceUnit,
    task: TaskDemand,
    route: RouteResult,
) -> bool:
    return (
        resource.available
        and task.required_capability in resource.capabilities
        and route.status is RouteStatus.REACHABLE
        and route.travel_minutes <= task.deadline_minutes
    )


def _reject_duplicates[T](values: Iterable[T], label: str) -> None:
    seen: set[T] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _binding_constraints(
    status: str,
    resources: tuple[ResourceUnit, ...],
    tasks: tuple[TaskDemand, ...],
    routes: tuple[TaskCandidateRoute, ...],
    eligible: dict[tuple[str, str], TaskCandidateRoute],
    selected: tuple[tuple[str, str], ...],
    uncovered: tuple[str, ...],
) -> tuple[str, ...]:
    resources_by_id = {item.resource_id: item for item in resources}
    tasks_by_id = {item.task_id: item for item in tasks}
    selected_by_resource = dict(selected)
    constraints: set[str] = set()
    for task_id in uncovered:
        task = tasks_by_id[task_id]
        if status not in _SOLUTION_STATUSES:
            constraints.add(
                f"solver-status: task={task_id}; status={status} produced no solution"
            )
            continue
        candidates = [item for item in routes if item.task_id == task_id]
        if not candidates:
            constraints.add(f"route: task={task_id}; no candidate route")
        for candidate in candidates:
            resource = resources_by_id[candidate.resource_id]
            prefix = f"resource={resource.resource_id}; task={task_id};"
            if not resource.available:
                constraints.add(f"availability: {prefix} resource is unavailable")
            elif task.required_capability not in resource.capabilities:
                constraints.add(
                    f"compatibility: {prefix} resource lacks capability="
                    f"{task.required_capability}"
                )
            elif candidate.route.status is not RouteStatus.REACHABLE:
                constraints.add(f"route: {prefix} route is unreachable")
            elif candidate.route.travel_minutes > task.deadline_minutes:
                constraints.add(
                    f"deadline: {prefix} travel_minutes="
                    f"{candidate.route.travel_minutes:g} exceeds deadline_minutes="
                    f"{task.deadline_minutes}"
                )
        eligible_resources = [
            resource_id
            for resource_id, candidate_task_id in eligible
            if candidate_task_id == task_id
        ]
        eligible_capacity = sum(
            resources_by_id[resource_id].capacity
            for resource_id in eligible_resources
        )
        if eligible_capacity < task.required_capacity:
            constraints.add(
                f"capacity: task={task_id}; eligible_capacity={eligible_capacity} "
                f"is below required_capacity={task.required_capacity}"
            )
        consumed = sorted(
            f"{resource_id}->{selected_by_resource[resource_id]}"
            for resource_id in eligible_resources
            if resource_id in selected_by_resource
            and selected_by_resource[resource_id] != task_id
        )
        if consumed:
            constraints.add(
                f"resource-contention: task={task_id}; eligible assignments="
                f"{', '.join(consumed)} consume needed capacity"
            )
    return tuple(sorted(constraints))
