from collections import defaultdict
from math import ceil

from hypothesis import given, settings, strategies as st

from wildfireops.decision.optimizer import (
    CandidateRoute,
    OptimizationRequest,
    solve_allocation,
)
from wildfireops.domain.operations import DemandPoint, ResourceUnit
from wildfireops.geospatial.road_graph import RouteResult, RouteStatus


@st.composite
def allocation_requests(draw: st.DrawFn) -> OptimizationRequest:
    resource_count = draw(st.integers(min_value=0, max_value=8))
    demand_count = draw(st.integers(min_value=0, max_value=8))
    capacities = draw(
        st.lists(
            st.integers(min_value=1, max_value=5),
            min_size=resource_count,
            max_size=resource_count,
        )
    )
    availability = draw(
        st.lists(
            st.booleans(),
            min_size=resource_count,
            max_size=resource_count,
        )
    )
    engine_capable = draw(
        st.lists(
            st.booleans(),
            min_size=resource_count,
            max_size=resource_count,
        )
    )
    required_capacities = draw(
        st.lists(
            st.integers(min_value=1, max_value=8),
            min_size=demand_count,
            max_size=demand_count,
        )
    )
    risks = draw(
        st.lists(
            st.integers(min_value=0, max_value=100),
            min_size=demand_count,
            max_size=demand_count,
        )
    )
    pair_count = resource_count * demand_count
    reachable = draw(st.lists(st.booleans(), min_size=pair_count, max_size=pair_count))
    half_minutes = draw(
        st.lists(
            st.integers(min_value=0, max_value=120),
            min_size=pair_count,
            max_size=pair_count,
        )
    )

    resources = tuple(
        ResourceUnit(
            f"resource-{index}",
            frozenset({"engine"} if engine_capable[index] else {"crew"}),
            capacities[index],
            availability[index],
            -121.6,
            39.8,
        )
        for index in range(resource_count)
    )
    demands = tuple(
        DemandPoint(
            f"destination-{index}",
            "engine",
            required_capacities[index],
            risks[index],
            -121.5,
            39.9,
        )
        for index in range(demand_count)
    )
    routes = tuple(
        CandidateRoute(
            resource.resource_id,
            demand.destination_id,
            RouteResult(
                RouteStatus.REACHABLE if reachable[index] else RouteStatus.UNREACHABLE,
                (),
                0.0,
                half_minutes[index] / 2,
                "graph-v1",
                "closures-v1",
            ),
        )
        for index, (resource, demand) in enumerate(
            (resource, demand) for resource in resources for demand in demands
        )
    )
    return OptimizationRequest(resources, demands, routes, max_response_minutes=30)


@given(allocation_requests())
@settings(max_examples=30, deadline=None)
def test_solution_invariants(request: OptimizationRequest) -> None:
    result = solve_allocation(request)

    assert result.status in {"FEASIBLE", "OPTIMAL"}
    resources = {resource.resource_id: resource for resource in request.resources}
    demands = {demand.destination_id: demand for demand in request.demands}
    routes = {
        (candidate.resource_id, candidate.destination_id): candidate.route
        for candidate in request.routes
    }
    assigned_resources = [assignment.resource_id for assignment in result.assignments]
    assigned_capacity: defaultdict[str, int] = defaultdict(int)

    assert len(assigned_resources) == len(set(assigned_resources))
    for assignment in result.assignments:
        resource = resources[assignment.resource_id]
        demand = demands[assignment.destination_id]
        route = routes[(assignment.resource_id, assignment.destination_id)]
        assert resource.available
        assert demand.required_capability in resource.capabilities
        assert route.status is RouteStatus.REACHABLE
        assert route.travel_minutes <= request.max_response_minutes
        assert assignment.capacity == resource.capacity
        assert assignment.travel_minutes == route.travel_minutes
        assigned_capacity[assignment.destination_id] += assignment.capacity

    for destination_id, capacity in assigned_capacity.items():
        assert capacity >= demands[destination_id].required_capacity

    assert set(assigned_capacity) == set(demands) - set(
        result.uncovered_destination_ids
    )
    assert result.assignments == tuple(
        sorted(
            result.assignments,
            key=lambda assignment: (
                assignment.resource_id,
                assignment.destination_id,
            ),
        )
    )
    assert result.uncovered_destination_ids == tuple(
        sorted(result.uncovered_destination_ids)
    )
    assert result.unassigned_resource_ids == tuple(
        sorted(result.unassigned_resource_ids)
    )
    assert result.binding_constraints == tuple(sorted(result.binding_constraints))
    assert result.travel_cost == sum(
        ceil(assignment.travel_minutes) for assignment in result.assignments
    )
    assert result.objective_value == (
        result.travel_cost + result.uncovered_risk_penalty
    )
