"""Deterministic constraint-based resource allocation."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil, isfinite

from ortools.sat.python import cp_model

from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


@dataclass(frozen=True, slots=True)
class CandidateRoute:
    resource_id: str
    destination_id: str
    route: RouteResult


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    resources: tuple[ResourceUnit, ...]
    demands: tuple[DemandPoint, ...]
    routes: tuple[CandidateRoute, ...]
    max_response_minutes: int
    max_solver_seconds: float = 2.0
    algorithm_version: str = "allocation-v1"


@dataclass(frozen=True, slots=True)
class Assignment:
    resource_id: str
    destination_id: str
    travel_minutes: float
    capacity: int


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    status: str
    assignments: tuple[Assignment, ...]
    uncovered_destination_ids: tuple[str, ...]
    travel_cost: int
    uncovered_risk_penalty: int
    objective_value: int
    runtime_milliseconds: int
    algorithm_version: str
    unassigned_resource_ids: tuple[str, ...] = ()
    binding_constraints: tuple[str, ...] = ()


_SOLUTION_STATUSES = frozenset({"FEASIBLE", "OPTIMAL"})
_PUBLIC_STATUSES = frozenset({"INFEASIBLE", "FEASIBLE", "OPTIMAL", "UNKNOWN"})


def solve_allocation(request: OptimizationRequest) -> OptimizationResult:
    resources, demands, routes = _validate_and_canonicalize(request)
    resources_by_id = {resource.resource_id: resource for resource in resources}
    demands_by_id = {demand.destination_id: demand for demand in demands}
    risk_penalties = {
        demand.destination_id: round(1000 * demand.weighted_risk / 100)
        for demand in demands
    }

    model = cp_model.CpModel()
    covered = {
        demand.destination_id: model.new_bool_var(f"covered[{demand.destination_id}]")
        for demand in demands
    }
    eligible_routes: dict[tuple[str, str], CandidateRoute] = {}
    excluded_reasons: dict[str, list[str]] = {
        demand.destination_id: [] for demand in demands
    }
    route_counts = {demand.destination_id: 0 for demand in demands}

    for candidate in routes:
        resource = resources_by_id[candidate.resource_id]
        demand = demands_by_id[candidate.destination_id]
        route_counts[demand.destination_id] += 1
        reason = _ineligibility_reason(resource, demand, candidate, request)
        if reason is None:
            eligible_routes[(resource.resource_id, demand.destination_id)] = candidate
        else:
            excluded_reasons[demand.destination_id].append(reason)

    assigned = {
        pair: model.new_bool_var(f"assigned[{pair[0]},{pair[1]}]")
        for pair in eligible_routes
    }
    for resource in resources:
        resource_vars = [
            variable
            for (resource_id, _), variable in assigned.items()
            if resource_id == resource.resource_id
        ]
        if resource_vars:
            model.add(sum(resource_vars) <= 1)

    for demand in demands:
        destination_vars = [
            (resources_by_id[resource_id].capacity, variable)
            for (resource_id, destination_id), variable in assigned.items()
            if destination_id == demand.destination_id
        ]
        if not destination_vars:
            model.add(covered[demand.destination_id] == 0)
            continue
        model.add(
            sum(capacity * variable for capacity, variable in destination_vars)
            >= demand.required_capacity * covered[demand.destination_id]
        )
        model.add(
            sum(variable for _, variable in destination_vars)
            <= len(destination_vars) * covered[demand.destination_id]
        )

    # CP-SAT requires integer coefficients; ceiling minutes conservatively avoids
    # understating fractional travel in the objective while eligibility uses raw time.
    travel_costs = {
        pair: ceil(candidate.route.travel_minutes)
        for pair, candidate in eligible_routes.items()
    }
    model.minimize(
        sum(travel_costs[pair] * variable for pair, variable in assigned.items())
        + sum(
            risk_penalties[destination_id] * (1 - variable)
            for destination_id, variable in covered.items()
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = request.max_solver_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    raw_status = solver.status_name(solver.solve(model))
    status = raw_status if raw_status in _PUBLIC_STATUSES else "UNKNOWN"
    runtime_milliseconds = round(solver.wall_time * 1000)

    if status in _SOLUTION_STATUSES:
        selected_pairs = tuple(
            pair for pair, variable in assigned.items() if solver.value(variable)
        )
        uncovered = tuple(
            destination_id
            for destination_id, variable in covered.items()
            if not solver.value(variable)
        )
    else:
        selected_pairs = ()
        uncovered = tuple(demands_by_id)

    assignments = tuple(
        Assignment(
            resource_id,
            destination_id,
            eligible_routes[(resource_id, destination_id)].route.travel_minutes,
            resources_by_id[resource_id].capacity,
        )
        for resource_id, destination_id in selected_pairs
    )
    selected_resource_ids = {assignment.resource_id for assignment in assignments}
    travel_cost = sum(travel_costs[pair] for pair in selected_pairs)
    uncovered_risk_penalty = sum(
        risk_penalties[destination_id] for destination_id in uncovered
    )
    binding_constraints = _binding_constraints(
        uncovered,
        demands_by_id,
        resources_by_id,
        eligible_routes,
        excluded_reasons,
        route_counts,
    )
    return OptimizationResult(
        status=status,
        assignments=assignments,
        uncovered_destination_ids=uncovered,
        travel_cost=travel_cost,
        uncovered_risk_penalty=uncovered_risk_penalty,
        objective_value=travel_cost + uncovered_risk_penalty,
        runtime_milliseconds=runtime_milliseconds,
        algorithm_version=request.algorithm_version,
        unassigned_resource_ids=tuple(
            resource.resource_id
            for resource in resources
            if resource.resource_id not in selected_resource_ids
        ),
        binding_constraints=binding_constraints,
    )


def _validate_and_canonicalize(
    request: OptimizationRequest,
) -> tuple[
    tuple[ResourceUnit, ...],
    tuple[DemandPoint, ...],
    tuple[CandidateRoute, ...],
]:
    if (
        isinstance(request.max_response_minutes, bool)
        or not isinstance(request.max_response_minutes, int)
        or request.max_response_minutes < 0
    ):
        raise ValueError("max_response_minutes must be a nonnegative integer")
    if (
        isinstance(request.max_solver_seconds, bool)
        or not isinstance(request.max_solver_seconds, int | float)
        or not isfinite(request.max_solver_seconds)
        or request.max_solver_seconds <= 0
    ):
        raise ValueError("max_solver_seconds must be a finite positive number")
    if (
        not isinstance(request.algorithm_version, str)
        or not request.algorithm_version.strip()
    ):
        raise ValueError("algorithm_version must be a nonblank string")

    duplicate_resource_ids = _duplicates(
        resource.resource_id for resource in request.resources
    )
    if duplicate_resource_ids:
        raise ValueError(f"duplicate resource ID: {duplicate_resource_ids[0]}")
    duplicate_destination_ids = _duplicates(
        demand.destination_id for demand in request.demands
    )
    if duplicate_destination_ids:
        raise ValueError(f"duplicate destination ID: {duplicate_destination_ids[0]}")

    resources = tuple(sorted(request.resources, key=lambda item: item.resource_id))
    demands = tuple(sorted(request.demands, key=lambda item: item.destination_id))
    resource_ids = {resource.resource_id for resource in resources}
    destination_ids = {demand.destination_id for demand in demands}
    for demand in demands:
        if (
            isinstance(demand.weighted_risk, bool)
            or not isinstance(demand.weighted_risk, int | float)
            or not isfinite(demand.weighted_risk)
            or not 0 <= demand.weighted_risk <= 100
        ):
            raise ValueError("weighted_risk must be finite and between 0 and 100")

    route_pairs = [
        (candidate.resource_id, candidate.destination_id)
        for candidate in request.routes
    ]
    duplicate_route_pairs = _duplicates(route_pairs)
    if duplicate_route_pairs:
        resource_id, destination_id = duplicate_route_pairs[0]
        raise ValueError(f"duplicate route pair: {resource_id} -> {destination_id}")
    routes = tuple(
        sorted(
            request.routes,
            key=lambda item: (item.resource_id, item.destination_id),
        )
    )
    for candidate in routes:
        if candidate.resource_id not in resource_ids:
            raise ValueError(f"unknown resource ID: {candidate.resource_id}")
        if candidate.destination_id not in destination_ids:
            raise ValueError(f"unknown destination ID: {candidate.destination_id}")
        travel_minutes = candidate.route.travel_minutes
        if (
            isinstance(travel_minutes, bool)
            or not isinstance(travel_minutes, int | float)
            or not isfinite(travel_minutes)
            or travel_minutes < 0
        ):
            raise ValueError("route travel_minutes must be finite and nonnegative")
    return resources, demands, routes


def _duplicates[T](items: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    duplicates: set[T] = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    return sorted(duplicates, key=str)


def _ineligibility_reason(
    resource: ResourceUnit,
    demand: DemandPoint,
    candidate: CandidateRoute,
    request: OptimizationRequest,
) -> str | None:
    prefix = f"resource={resource.resource_id}; destination={demand.destination_id};"
    if not resource.available:
        return f"availability: {prefix} resource is unavailable"
    if demand.required_capability not in resource.capabilities:
        return (
            f"compatibility: {prefix} resource lacks capability="
            f"{demand.required_capability}"
        )
    if candidate.route.status != RouteStatus.REACHABLE:
        return f"route: {prefix} route is unreachable"
    if candidate.route.travel_minutes > request.max_response_minutes:
        return (
            f"response-time: {prefix} travel_minutes="
            f"{candidate.route.travel_minutes:g} exceeds max_response_minutes="
            f"{request.max_response_minutes}"
        )
    return None


def _binding_constraints(
    uncovered: tuple[str, ...],
    demands: dict[str, DemandPoint],
    resources: dict[str, ResourceUnit],
    eligible_routes: dict[tuple[str, str], CandidateRoute],
    excluded_reasons: dict[str, list[str]],
    route_counts: dict[str, int],
) -> tuple[str, ...]:
    constraints: set[str] = set()
    for destination_id in uncovered:
        demand = demands[destination_id]
        constraints.update(excluded_reasons[destination_id])
        if route_counts[destination_id] == 0:
            constraints.add(
                f"route: destination={destination_id}; no candidate route was provided"
            )
        eligible_capacity = sum(
            resources[resource_id].capacity
            for resource_id, candidate_destination_id in eligible_routes
            if candidate_destination_id == destination_id
        )
        if eligible_capacity < demand.required_capacity:
            constraints.add(
                f"capacity: destination={destination_id}; eligible capacity="
                f"{eligible_capacity} is below required capacity="
                f"{demand.required_capacity}"
            )
        else:
            constraints.add(
                f"capacity: destination={destination_id}; required capacity="
                f"{demand.required_capacity} was not satisfied by selected assignments"
            )
    return tuple(sorted(constraints))
