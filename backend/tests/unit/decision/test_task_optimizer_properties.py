from hypothesis import given, settings, strategies as st

from wildfireops.decision.task_optimizer import (
    TaskCandidateRoute,
    TaskDemand,
    TaskOptimizationRequest,
    solve_task_plan,
)
from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


@st.composite
def task_plan_requests(draw: st.DrawFn) -> TaskOptimizationRequest:
    resource_count = draw(st.integers(min_value=1, max_value=4))
    task_count = draw(st.integers(min_value=1, max_value=4))
    resources = tuple(
        ResourceUnit(
            f"resource-{index}",
            frozenset({"protect"} if index % 2 == 0 else {"transport"}),
            draw(st.integers(min_value=1, max_value=3)),
            draw(st.booleans()),
            -121.60 - index / 100,
            39.80 + index / 100,
        )
        for index in range(resource_count)
    )
    tasks = tuple(
        TaskDemand(
            f"task-{index}",
            "park-fire" if index % 2 == 0 else "spot-fire",
            f"asset-{index}",
            "protect" if index % 2 == 0 else "transport",
            draw(st.integers(min_value=1, max_value=4)),
            draw(st.integers(min_value=5, max_value=60)),
            draw(st.integers(min_value=0, max_value=2_000)),
        )
        for index in range(task_count)
    )
    routes = tuple(
        TaskCandidateRoute(
            resource.resource_id,
            task.task_id,
            RouteResult(
                draw(st.sampled_from(tuple(RouteStatus))),
                (),
                1_000,
                draw(
                    st.floats(
                        min_value=1,
                        max_value=90,
                        allow_nan=False,
                        allow_infinity=False,
                    )
                ),
                "graph-v1",
                "closures-v1",
            ),
        )
        for resource in resources
        for task in tasks
    )
    return TaskOptimizationRequest(
        resources=resources,
        tasks=tasks,
        routes=routes,
        locked_assignments=(),
        travel_weight=draw(st.integers(min_value=0, max_value=10)),
    )


@given(task_plan_requests())
@settings(max_examples=30, deadline=None)
def test_task_plan_invariants(request: TaskOptimizationRequest) -> None:
    result = solve_task_plan(request)
    resources = {item.resource_id: item for item in request.resources}
    tasks = {item.task_id: item for item in request.tasks}
    routes = {
        (item.resource_id, item.task_id): item.route for item in request.routes
    }
    assigned_resources = [item.resource_id for item in result.assignments]

    assert len(assigned_resources) == len(set(assigned_resources))
    assert result.assignments == tuple(
        sorted(result.assignments, key=lambda item: (item.resource_id, item.task_id))
    )
    assert result.uncovered_task_ids == tuple(sorted(result.uncovered_task_ids))
    for assignment in result.assignments:
        resource = resources[assignment.resource_id]
        task = tasks[assignment.task_id]
        route = routes[(assignment.resource_id, assignment.task_id)]
        assert resource.available
        assert task.required_capability in resource.capabilities
        assert route.status is RouteStatus.REACHABLE
        assert route.travel_minutes <= task.deadline_minutes
    for task_id in set(tasks) - set(result.uncovered_task_ids):
        assert sum(
            item.capacity for item in result.assignments if item.task_id == task_id
        ) >= tasks[task_id].required_capacity
    assert result.objective_value == result.travel_cost + result.uncovered_task_penalty
