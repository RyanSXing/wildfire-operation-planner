from dataclasses import replace

import pytest

from wildfireops.decision import task_optimizer as task_optimizer_module
from wildfireops.decision.task_optimizer import (
    LockedTaskAssignment,
    TaskAssignment,
    TaskCandidateRoute,
    TaskDemand,
    TaskOptimizationRequest,
    solve_task_plan,
)
from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


def route(minutes: float) -> RouteResult:
    return RouteResult(
        RouteStatus.REACHABLE,
        (),
        minutes * 1000,
        minutes,
        "graph-v1",
        "closures-v1",
    )


def resource(
    resource_id: str,
    *,
    capabilities: frozenset[str] = frozenset({"protect"}),
    capacity: int = 1,
    available: bool = True,
) -> ResourceUnit:
    return ResourceUnit(
        resource_id,
        capabilities,
        capacity,
        available,
        -121.6,
        39.8,
    )


def task(
    task_id: str,
    *,
    incident_id: str = "park-fire",
    asset_id: str = "asset-a",
    capability: str = "protect",
    capacity: int = 1,
    deadline: int = 30,
    penalty: int = 200,
) -> TaskDemand:
    return TaskDemand(
        task_id,
        incident_id,
        asset_id,
        capability,
        capacity,
        deadline,
        penalty,
    )


def candidate(
    resource_id: str,
    task_id: str,
    minutes: float,
    status: RouteStatus = RouteStatus.REACHABLE,
) -> TaskCandidateRoute:
    return TaskCandidateRoute(
        resource_id,
        task_id,
        RouteResult(status, (), minutes * 1000, minutes, "graph-v1", "closures-v1"),
    )


def assert_result(
    result: object,
    *,
    assignments: tuple[TaskAssignment, ...],
    uncovered: tuple[str, ...],
    unassigned: tuple[str, ...],
    travel_cost: int,
    penalty: int,
    constraints: tuple[str, ...],
) -> None:
    assert getattr(result, "assignments") == assignments
    assert getattr(result, "uncovered_task_ids") == uncovered
    assert getattr(result, "unassigned_resource_ids") == unassigned
    assert getattr(result, "travel_cost") == travel_cost
    assert getattr(result, "uncovered_task_penalty") == penalty
    assert getattr(result, "objective_value") == travel_cost + penalty
    assert getattr(result, "binding_constraints") == constraints


def test_shared_resource_goes_to_higher_penalty_task_across_incidents() -> None:
    engine = resource("engine-1")
    tasks = (
        TaskDemand("park-task", "park-fire", "asset-a", "protect", 1, 30, 200),
        TaskDemand("spot-task", "spot-fire", "asset-b", "protect", 1, 30, 900),
    )
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(engine,),
            tasks=tasks,
            routes=(
                TaskCandidateRoute("engine-1", "park-task", route(2)),
                TaskCandidateRoute("engine-1", "spot-task", route(5)),
            ),
            locked_assignments=(),
            travel_weight=1,
            max_solver_seconds=2,
        )
    )

    assert result.status == "OPTIMAL"
    assert_result(
        result,
        assignments=(
            TaskAssignment("engine-1", "spot-task", "spot-fire", "asset-b", 5, 1),
        ),
        uncovered=("park-task",),
        unassigned=(),
        travel_cost=5,
        penalty=200,
        constraints=(
            "resource-contention: task=park-task; eligible assignments="
            "engine-1->spot-task consume needed capacity",
        ),
    )


def test_multiple_resources_may_combine_capacity_for_one_task() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("bus-a"), resource("bus-b")),
            tasks=(task("evacuation-1", capacity=2),),
            routes=(
                candidate("bus-a", "evacuation-1", 2),
                candidate("bus-b", "evacuation-1", 3),
            ),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(
            TaskAssignment("bus-a", "evacuation-1", "park-fire", "asset-a", 2, 1),
            TaskAssignment("bus-b", "evacuation-1", "park-fire", "asset-a", 3, 1),
        ),
        uncovered=(),
        unassigned=(),
        travel_cost=5,
        penalty=0,
        constraints=(),
    )


def test_one_resource_cannot_cover_tasks_from_both_incidents() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1"),),
            tasks=(
                task("park-task", penalty=200),
                task(
                    "spot-task",
                    incident_id="spot-fire",
                    asset_id="asset-b",
                    penalty=900,
                ),
            ),
            routes=(
                candidate("engine-1", "park-task", 2),
                candidate("engine-1", "spot-task", 5),
            ),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(
            TaskAssignment("engine-1", "spot-task", "spot-fire", "asset-b", 5, 1),
        ),
        uncovered=("park-task",),
        unassigned=(),
        travel_cost=5,
        penalty=200,
        constraints=(
            "resource-contention: task=park-task; eligible assignments="
            "engine-1->spot-task consume needed capacity",
        ),
    )


def test_unavailable_resource_is_ineligible() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1", available=False),),
            tasks=(task("protect-1"),),
            routes=(candidate("engine-1", "protect-1", 2),),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(),
        uncovered=("protect-1",),
        unassigned=("engine-1",),
        travel_cost=0,
        penalty=200,
        constraints=(
            "availability: resource=engine-1; task=protect-1; resource is unavailable",
            "capacity: task=protect-1; eligible_capacity=0 is below "
            "required_capacity=1",
        ),
    )


def test_incompatible_resource_is_ineligible() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("bus-1", capabilities=frozenset({"transport"})),),
            tasks=(task("medical-1", capability="medical"),),
            routes=(candidate("bus-1", "medical-1", 2),),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(),
        uncovered=("medical-1",),
        unassigned=("bus-1",),
        travel_cost=0,
        penalty=200,
        constraints=(
            "capacity: task=medical-1; eligible_capacity=0 is below "
            "required_capacity=1",
            "compatibility: resource=bus-1; task=medical-1; resource lacks "
            "capability=medical",
        ),
    )


def test_late_route_is_ineligible() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1"),),
            tasks=(task("protect-1"),),
            routes=(candidate("engine-1", "protect-1", 31),),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(),
        uncovered=("protect-1",),
        unassigned=("engine-1",),
        travel_cost=0,
        penalty=200,
        constraints=(
            "capacity: task=protect-1; eligible_capacity=0 is below "
            "required_capacity=1",
            "deadline: resource=engine-1; task=protect-1; travel_minutes=31 "
            "exceeds deadline_minutes=30",
        ),
    )


def test_unreachable_route_is_ineligible() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1"),),
            tasks=(task("protect-1"),),
            routes=(
                candidate("engine-1", "protect-1", 2, RouteStatus.UNREACHABLE),
            ),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(),
        uncovered=("protect-1",),
        unassigned=("engine-1",),
        travel_cost=0,
        penalty=200,
        constraints=(
            "capacity: task=protect-1; eligible_capacity=0 is below "
            "required_capacity=1",
            "route: resource=engine-1; task=protect-1; route is unreachable",
        ),
    )


def test_valid_locked_assignment_is_forced() -> None:
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1"),),
            tasks=(
                task("park-task", penalty=200),
                task(
                    "spot-task",
                    incident_id="spot-fire",
                    asset_id="asset-b",
                    penalty=900,
                ),
            ),
            routes=(
                candidate("engine-1", "park-task", 2),
                candidate("engine-1", "spot-task", 5),
            ),
            locked_assignments=(LockedTaskAssignment("engine-1", "park-task"),),
            travel_weight=1,
        )
    )

    assert_result(
        result,
        assignments=(
            TaskAssignment("engine-1", "park-task", "park-fire", "asset-a", 2, 1),
        ),
        uncovered=("spot-task",),
        unassigned=(),
        travel_cost=2,
        penalty=900,
        constraints=(
            "resource-contention: task=spot-task; eligible assignments="
            "engine-1->park-task consume needed capacity",
        ),
    )


def test_invalid_locked_assignment_fails_before_solving() -> None:
    request = TaskOptimizationRequest(
        resources=(resource("bus-1", capabilities=frozenset({"transport"})),),
        tasks=(task("medical-1", capability="medical"),),
        routes=(candidate("bus-1", "medical-1", 2),),
        locked_assignments=(LockedTaskAssignment("bus-1", "medical-1"),),
        travel_weight=1,
    )

    with pytest.raises(
        ValueError,
        match="locked assignment is not eligible: bus-1 -> medical-1",
    ):
        solve_task_plan(request)


def test_unknown_solver_status_does_not_read_variable_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Parameters:
        pass

    class UnknownSolver:
        def __init__(self) -> None:
            self.parameters = Parameters()
            self.wall_time = 0.0

        def solve(self, model: object) -> object:
            return model

        def status_name(self, status: object) -> str:
            return "UNKNOWN"

        def value(self, variable: object) -> int:
            raise AssertionError(f"value read for non-solution variable {variable}")

    monkeypatch.setattr(task_optimizer_module.cp_model, "CpSolver", UnknownSolver)
    result = solve_task_plan(
        TaskOptimizationRequest(
            resources=(resource("engine-1"),),
            tasks=(task("protect-1"),),
            routes=(candidate("engine-1", "protect-1", 2),),
            locked_assignments=(),
            travel_weight=1,
        )
    )

    assert result.status == "UNKNOWN"
    assert_result(
        result,
        assignments=(),
        uncovered=("protect-1",),
        unassigned=("engine-1",),
        travel_cost=0,
        penalty=200,
        constraints=(
            "solver-status: task=protect-1; status=UNKNOWN produced no solution",
        ),
    )


def test_reordered_inputs_produce_identical_semantic_result() -> None:
    request = TaskOptimizationRequest(
        resources=(resource("engine-b"), resource("engine-a")),
        tasks=(
            task("spot-task", incident_id="spot-fire", asset_id="asset-b", penalty=900),
            task("park-task", penalty=200),
        ),
        routes=(
            candidate("engine-b", "spot-task", 5),
            candidate("engine-a", "park-task", 2),
            candidate("engine-a", "spot-task", 3),
            candidate("engine-b", "park-task", 4),
        ),
        locked_assignments=(LockedTaskAssignment("engine-a", "park-task"),),
        travel_weight=1,
    )

    forward = solve_task_plan(request)
    reversed_result = solve_task_plan(
        replace(
            request,
            resources=tuple(reversed(request.resources)),
            tasks=tuple(reversed(request.tasks)),
            routes=tuple(reversed(request.routes)),
            locked_assignments=tuple(reversed(request.locked_assignments)),
        )
    )

    assert replace(forward, runtime_milliseconds=0) == replace(
        reversed_result,
        runtime_milliseconds=0,
    )
