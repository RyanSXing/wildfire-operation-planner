"""Deterministic JSON-compatible allocation explanations."""

from wildfireops.decision.optimizer import OptimizationResult


def explain_result(result: OptimizationResult) -> dict[str, object]:
    selected_assignments = [
        {
            "resource_id": assignment.resource_id,
            "destination_id": assignment.destination_id,
            "travel_minutes": assignment.travel_minutes,
            "capacity": assignment.capacity,
            "rationale": (
                f"{assignment.resource_id} supplies capacity {assignment.capacity} "
                f"to {assignment.destination_id} with "
                f"{assignment.travel_minutes:g}-minute travel."
            ),
        }
        for assignment in sorted(
            result.assignments,
            key=lambda item: (item.resource_id, item.destination_id),
        )
    ]
    uncovered_destinations = []
    binding_constraints = sorted(result.binding_constraints)
    for destination_id in sorted(result.uncovered_destination_ids):
        marker = f"destination={destination_id};"
        reasons = [
            constraint for constraint in binding_constraints if marker in constraint
        ]
        uncovered_destinations.append(
            {
                "destination_id": destination_id,
                "limiting_reason": "; ".join(reasons)
                or "No feasible assignment was selected.",
            }
        )
    return {
        "status": result.status,
        "runtime_milliseconds": result.runtime_milliseconds,
        "algorithm_version": result.algorithm_version,
        "selected_assignments": selected_assignments,
        "uncovered_destinations": uncovered_destinations,
        "unassigned_resource_ids": sorted(result.unassigned_resource_ids),
        "binding_constraints": binding_constraints,
        "objective_components": {
            "travel_cost": result.travel_cost,
            "uncovered_risk_penalty": result.uncovered_risk_penalty,
            "objective_value": result.objective_value,
        },
    }
