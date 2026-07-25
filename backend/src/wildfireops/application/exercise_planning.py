"""Deterministic, session-scoped exercise plan materialization."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import cast
from uuid import UUID

from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseEvent,
    ExercisePlanRun,
    ExerciseRepositoryProtocol,
    ExerciseSession,
    ExerciseSessionService,
    ExerciseTransitionInvalid,
    ExerciseVersionConflict,
    _copy_json_object,
    _event_inputs,
    _json_for_storage,
    _require_definition,
    _session_from_state,
    _session_state,
    _validate_replay_snapshot,
    session_projection,
)
from wildfireops.decision.task_explanations import (
    explain_task_plan,
    serialize_task_explanation,
)
from wildfireops.decision.task_optimizer import (
    TASK_ALGORITHM_VERSION,
    LockedTaskAssignment,
    TaskCandidateRoute,
    TaskDemand,
    TaskOptimizationRequest,
    TaskOptimizationResult,
    solve_task_plan,
)
from wildfireops.domain.observations import freeze_json_object
from wildfireops.domain.operations import ResourceUnit
from wildfireops.geospatial.road_graph import (
    RoadGraph,
    RouteResult,
    RouteStatus,
    compute_route,
    nearest_road_node,
)
from wildfireops.replay.exercise import (
    ExerciseDefinition,
    ExerciseTask,
    ObjectivePreset,
    ObjectiveWeights,
)


@dataclass(frozen=True, slots=True)
class MaterializedCheckpoint:
    checkpoint_key: str
    objective: ObjectivePreset
    tasks: tuple[TaskDemand, ...]
    resources: tuple[ResourceUnit, ...]
    closed_edge_ids: tuple[str, ...]
    asset_positions: Mapping[str, tuple[float, float]]
    asset_sources: Mapping[str, Mapping[str, str]]
    wind: Mapping[str, float] | None
    source_versions: Mapping[str, object]
    incidents: tuple[Mapping[str, object], ...]


def uncovered_penalty(task: ExerciseTask, weights: ObjectiveWeights) -> int:
    return (
        weights.base_priority_weight * task.base_priority
        + weights.critical_service_weight * int(task.critical_service)
        + weights.population_weight
        * (task.affected_population // weights.population_divisor)
    )


def planning_input_hash(payload: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            _copy_json_object(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def materialize_checkpoint(
    definition: ExerciseDefinition,
    *,
    checkpoint_index: int,
    objective: ObjectivePreset,
    consequences: Mapping[str, object],
) -> MaterializedCheckpoint:
    checkpoint = definition.checkpoints[checkpoint_index]
    weights = definition.objectives[objective]
    assets = {item.asset_id: item for item in definition.assets}
    task_assets = {item.asset_id for item in checkpoint.tasks}
    closed = () if checkpoint.disruption is None else checkpoint.disruption.closed_edge_ids
    if checkpoint_index == 2 and consequences.get("corridorCleared") is True:
        prior = definition.checkpoints[1].disruption
        prior_closed = () if prior is None else prior.closed_edge_ids
        closed = tuple(edge_id for edge_id in closed if edge_id not in prior_closed)
    return MaterializedCheckpoint(
        checkpoint_key=checkpoint.checkpoint_key,
        objective=objective,
        tasks=tuple(
            TaskDemand(
                item.task_id,
                item.incident_key,
                item.asset_id,
                item.required_capability,
                item.required_capacity,
                item.deadline_minutes,
                uncovered_penalty(item, weights),
            )
            for item in sorted(checkpoint.tasks, key=lambda item: item.task_id)
        ),
        resources=tuple(
            ResourceUnit(
                item.resource_id,
                item.capabilities,
                item.capacity,
                item.available,
                item.position.longitude,
                item.position.latitude,
            )
            for item in sorted(definition.resources, key=lambda item: item.resource_id)
        ),
        closed_edge_ids=tuple(sorted(closed)),
        asset_positions=cast(Mapping[str, tuple[float, float]], freeze_json_object({
            asset_id: (assets[asset_id].position.longitude, assets[asset_id].position.latitude)
            for asset_id in sorted(task_assets)
        })),
        asset_sources=cast(Mapping[str, Mapping[str, str]], freeze_json_object({
            asset_id: {
                "sourceName": assets[asset_id].source_name,
                "sourceVersion": assets[asset_id].source_version,
                "sourceRecordId": assets[asset_id].source_record_id,
                "citationUrl": assets[asset_id].citation_url,
                "provenance": assets[asset_id].provenance,
            }
            for asset_id in sorted(task_assets)
        })),
        wind=(
            None
            if checkpoint.disruption is None
            else cast(Mapping[str, float], freeze_json_object({
                "speedMps": checkpoint.disruption.wind_speed_mps,
                "directionDegrees": checkpoint.disruption.wind_direction_degrees,
            }))
        ),
        source_versions=freeze_json_object({
            "exercise": definition.version,
            "graph": definition.graph_version,
            "replayPackage": definition.replay_package_id,
            "historicalWeatherIdentity": checkpoint.historical_weather_identity,
        }),
        incidents=tuple(
            freeze_json_object(
                {
                    "incidentId": item.incident_key,
                    "provenance": item.provenance,
                    "detectionIdentities": list(item.detection_identities),
                    "simulatedPosition": (
                        None
                        if item.simulated_position is None
                        else [
                            item.simulated_position.longitude,
                            item.simulated_position.latitude,
                        ]
                    ),
                }
            )
            for item in sorted(checkpoint.incidents, key=lambda item: item.incident_key)
        ),
    )


def candidate_routes(
    graph: RoadGraph,
    resources: tuple[ResourceUnit, ...],
    tasks: tuple[TaskDemand, ...],
    asset_positions: Mapping[str, tuple[float, float]],
    closed_edge_ids: tuple[str, ...],
) -> tuple[TaskCandidateRoute, ...]:
    return tuple(
        TaskCandidateRoute(
            resource.resource_id,
            task.task_id,
            compute_route(
                graph,
                nearest_road_node(graph, resource.longitude, resource.latitude),
                nearest_road_node(graph, *asset_positions[task.asset_id]),
                closed_edge_ids,
            ),
        )
        for resource in resources
        for task in tasks
    )


def serialize_planning_input(
    checkpoint: MaterializedCheckpoint,
    routes: tuple[TaskCandidateRoute, ...],
    locked_assignments: tuple[LockedTaskAssignment, ...] = (),
) -> dict[str, object]:
    return {
        "checkpointKey": checkpoint.checkpoint_key,
        "objective": checkpoint.objective,
        "closedEdgeIds": list(checkpoint.closed_edge_ids),
        "wind": checkpoint.wind,
        "resources": [
            {
                "resourceId": item.resource_id,
                "capabilities": sorted(item.capabilities),
                "capacity": item.capacity,
                "available": item.available,
                "longitude": item.longitude,
                "latitude": item.latitude,
            }
            for item in checkpoint.resources
        ],
        "tasks": [
            {
                "taskId": item.task_id,
                "incidentId": item.incident_id,
                "assetId": item.asset_id,
                "requiredCapability": item.required_capability,
                "requiredCapacity": item.required_capacity,
                "deadlineMinutes": item.deadline_minutes,
                "penalty": item.uncovered_penalty,
                "position": list(checkpoint.asset_positions[item.asset_id]),
                "assetSource": dict(checkpoint.asset_sources[item.asset_id]),
            }
            for item in checkpoint.tasks
        ],
        "routes": [
            {
                "resourceId": item.resource_id,
                "taskId": item.task_id,
                "status": item.route.status.value,
                "edgeIds": list(item.route.edge_ids),
                "distanceMeters": item.route.distance_meters,
                "travelMinutes": item.route.travel_minutes,
                "graphVersion": item.route.graph_version,
                "closureHash": item.route.closure_hash,
            }
            for item in routes
        ],
        "lockedAssignments": [
            {"resourceId": item.resource_id, "taskId": item.task_id}
            for item in sorted(
                locked_assignments, key=lambda item: (item.resource_id, item.task_id)
            )
        ],
        "sourceVersions": dict(checkpoint.source_versions),
        "incidents": [dict(item) for item in checkpoint.incidents],
    }


def serialize_task_result(
    result: TaskOptimizationResult,
    routes: tuple[TaskCandidateRoute, ...],
    checkpoint: MaterializedCheckpoint,
) -> dict[str, object]:
    route_by_pair = {(item.resource_id, item.task_id): item.route for item in routes}
    resources = {item.resource_id: item for item in checkpoint.resources}
    tasks = {item.task_id: item for item in checkpoint.tasks}
    supplied = {
        task_id: sum(item.capacity for item in result.assignments if item.task_id == task_id)
        for task_id in tasks
    }
    return {
        "status": result.status,
        "assignments": [
            {
                "resourceId": item.resource_id,
                "taskId": item.task_id,
                "incidentId": item.incident_id,
                "assetId": item.asset_id,
                "capacity": item.capacity,
                "travelMinutes": item.travel_minutes,
                "route": _serialize_route(route_by_pair[item.resource_id, item.task_id]),
            }
            for item in result.assignments
        ],
        "uncoveredTaskIds": list(result.uncovered_task_ids),
        "coveredTaskIds": [
            task_id for task_id in tasks if task_id not in result.uncovered_task_ids
        ],
        "taskCoverage": [
            {
                "taskId": task_id,
                "requiredCapacity": task.required_capacity,
                "suppliedCapacity": supplied[task_id],
                "covered": task_id not in result.uncovered_task_ids,
            }
            for task_id, task in tasks.items()
        ],
        "candidateFacts": [
            {
                "resourceId": route.resource_id,
                "taskId": route.task_id,
                "available": resources[route.resource_id].available,
                "capabilityCompatible": tasks[route.task_id].required_capability
                in resources[route.resource_id].capabilities,
                "routeReachable": route.route.status is RouteStatus.REACHABLE,
                "travelMinutes": route.route.travel_minutes,
                "deadlineMinutes": tasks[route.task_id].deadline_minutes,
                "eligible": (
                    resources[route.resource_id].available
                    and tasks[route.task_id].required_capability
                    in resources[route.resource_id].capabilities
                    and route.route.status is RouteStatus.REACHABLE
                    and route.route.travel_minutes <= tasks[route.task_id].deadline_minutes
                ),
            }
            for route in routes
        ],
        "unassignedResourceIds": list(result.unassigned_resource_ids),
        "objectiveComponents": {
            "travelCost": result.travel_cost,
            "uncoveredTaskPenalty": result.uncovered_task_penalty,
            "objectiveValue": result.objective_value,
        },
        "bindingConstraints": list(result.binding_constraints),
        "runtimeMilliseconds": result.runtime_milliseconds,
        "algorithmVersion": result.algorithm_version,
    }


def _serialize_route(route: RouteResult) -> dict[str, object]:
    return {
        "status": route.status.value,
        "edgeIds": list(route.edge_ids),
        "distanceMeters": route.distance_meters,
        "travelMinutes": route.travel_minutes,
    }


class ExercisePlanningService:
    def __init__(
        self,
        *,
        definition: ExerciseDefinition,
        definition_digest: str,
        graph: RoadGraph,
        repository: ExerciseRepositoryProtocol,
        session_service: ExerciseSessionService,
        clock: Callable[[], datetime],
    ) -> None:
        if graph.graph_version != definition.graph_version:
            raise ValueError("road graph version does not match exercise definition")
        self._definition = definition
        self._definition_digest = definition_digest
        self._graph = graph
        self._repository = repository
        self._session_service = session_service
        self._clock = clock

    async def generate_plan(
        self,
        session_id: UUID,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[ExercisePlanRun, dict[str, object]]:
        session, claim, replayed = await self._session_service.lock_command(
            session_id, expected_version, idempotency_key, "generate-plan", {}
        )
        _require_definition(session, self._definition, self._definition_digest)
        if replayed is not None:
            return await self._replay(session_id, replayed)
        if session.objective is None:
            raise ExerciseTransitionInvalid("select an objective before planning")
        if session.checkpoint_index == 2:
            latest = await self._repository.latest_plan(session.id, "field-report")
            if latest is not None and latest.output_data.get("operatorOverride"):
                raise ExerciseTransitionInvalid("checkpoint-three override is already applied")
        checkpoint = materialize_checkpoint(
            self._definition,
            checkpoint_index=session.checkpoint_index,
            objective=session.objective,
            consequences=session.consequences,
        )
        routes = candidate_routes(
            self._graph,
            checkpoint.resources,
            checkpoint.tasks,
            checkpoint.asset_positions,
            checkpoint.closed_edge_ids,
        )
        payload = self._payload(checkpoint, routes, session.consequences)
        result = solve_task_plan(
            TaskOptimizationRequest(
                checkpoint.resources,
                checkpoint.tasks,
                routes,
                (),
                self._definition.objectives[session.objective].travel_weight,
                max_solver_seconds=2,
            )
        )
        previous = await self._repository.latest_plan_for_session(session.id)
        output = serialize_task_result(result, routes, checkpoint)
        output["explanation"] = serialize_task_explanation(
            explain_task_plan(
                None
                if previous is None
                else {
                    **dict(previous.input_data),
                    "assignments": previous.output_data.get("assignments", []),
                },
                {**payload, "assignments": output["assignments"]},
            )
        )
        return await self._store_plan(
            session,
            claim.id,
            expected_version,
            "exercise.plan-generated",
            payload,
            output,
            checkpoint.checkpoint_key,
            {"inputHash": planning_input_hash(payload)},
        )

    async def apply_override(
        self,
        session_id: UUID,
        *,
        resource_id: str,
        task_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[ExercisePlanRun, dict[str, object]]:
        session, claim, replayed = await self._session_service.lock_command(
            session_id,
            expected_version,
            idempotency_key,
            "apply-override",
            {"resourceId": resource_id, "taskId": task_id},
        )
        _require_definition(session, self._definition, self._definition_digest)
        if replayed is not None:
            return await self._replay(session_id, replayed)
        if session.checkpoint_index != 2:
            raise ExerciseTransitionInvalid("override requires checkpoint three")
        if task_id != "shelter-capacity-transport":
            raise ExerciseCommandInvalid("guided override must target shelter transport")
        resource = next(
            (
                item
                for item in self._definition.resources
                if item.resource_id == resource_id
            ),
            None,
        )
        if resource is None or resource.resource_type != "evacuation-bus":
            raise ExerciseCommandInvalid(
                "override fails capability, capacity, route, deadline, or uniqueness"
            )
        if session.objective is None:
            raise ExerciseTransitionInvalid("select an objective before overriding")
        current = await self._repository.latest_plan(session.id, "field-report")
        if current is None:
            raise ExerciseTransitionInvalid("generate checkpoint-three plan first")
        if current.output_data.get("operatorOverride"):
            raise ExerciseTransitionInvalid("checkpoint-three override is already applied")
        if current.output_data.get("status") not in {"FEASIBLE", "OPTIMAL"}:
            raise ExerciseTransitionInvalid("generate checkpoint-three plan first")
        if (
            current.input_data.get("objective") != session.objective
            or current.versions.get("definitionDigest") != self._definition_digest
            or current.versions.get("exercise") != self._definition.version
            or current.versions.get("graph") != self._definition.graph_version
            or current.versions.get("taskAlgorithm") != TASK_ALGORITHM_VERSION
        ):
            raise ExerciseVersionConflict("checkpoint planning input changed")
        checkpoint = materialize_checkpoint(
            self._definition,
            checkpoint_index=session.checkpoint_index,
            objective=session.objective,
            consequences=session.consequences,
        )
        routes = candidate_routes(
            self._graph,
            checkpoint.resources,
            checkpoint.tasks,
            checkpoint.asset_positions,
            checkpoint.closed_edge_ids,
        )
        base_payload = self._payload(checkpoint, routes, session.consequences)
        if (
            planning_input_hash(current.input_data) != current.input_hash
            or planning_input_hash(base_payload) != current.input_hash
            or current.input_data != freeze_json_object(base_payload)
        ):
            raise ExerciseVersionConflict("checkpoint planning input changed")
        locked = (LockedTaskAssignment(resource_id, task_id),)
        payload = self._payload(checkpoint, routes, session.consequences, locked)
        try:
            request = TaskOptimizationRequest(
                checkpoint.resources,
                checkpoint.tasks,
                routes,
                locked,
                self._definition.objectives[session.objective].travel_weight,
                max_solver_seconds=2,
            )
            result = solve_task_plan(request)
        except ValueError as error:
            raise ExerciseCommandInvalid(
                "override fails capability, capacity, route, deadline, or uniqueness"
            ) from error
        if not any(
            item.resource_id == resource_id and item.task_id == task_id
            for item in result.assignments
        ):
            raise ExerciseCommandInvalid(
                "override fails capability, capacity, route, deadline, or uniqueness"
            )
        output = serialize_task_result(result, routes, checkpoint)
        output["explanation"] = serialize_task_explanation(
            explain_task_plan(
                {
                    **dict(current.input_data),
                    "assignments": current.output_data.get("assignments", []),
                },
                {**payload, "assignments": output["assignments"]},
            )
        )
        output["operatorOverride"] = {
            "resourceId": resource_id,
            "taskId": task_id,
            "beforePlanId": str(current.id),
        }
        explanation = cast(Mapping[str, object], output["explanation"])
        changes = explanation["changes"]
        assert isinstance(changes, list)
        changed = any(
            current.output_data.get(key) != output.get(key)
            for key in (
                "assignments",
                "coveredTaskIds",
                "uncoveredTaskIds",
                "objectiveComponents",
            )
        )
        changes.extend(
            [
                {
                    "code": "override.locked-assignment",
                    "summary": "The operator locked the requested assignment.",
                    "evidence": {"resourceId": resource_id, "taskId": task_id},
                },
                {
                    "code": (
                        "operator.override-changed-plan"
                        if changed
                        else "operator.override-validated"
                    ),
                    "summary": (
                        "The operator override changed the stored plan."
                        if changed
                        else "The requested operator lock was validated and recorded."
                    ),
                    "evidence": {
                        "resourceId": resource_id,
                        "taskId": task_id,
                        "beforePlanId": str(current.id),
                        "before": current.output_data.get("objectiveComponents"),
                        "after": output.get("objectiveComponents"),
                    },
                },
            ]
        )
        return await self._store_plan(
            session,
            claim.id,
            expected_version,
            "exercise.override-applied",
            payload,
            output,
            checkpoint.checkpoint_key,
            {
                "beforePlanId": str(current.id),
                "resourceId": resource_id,
                "taskId": task_id,
            },
        )

    async def _store_plan(
        self,
        session: ExerciseSession,
        claim_id: UUID,
        expected_version: int,
        event_type: str,
        payload: dict[str, object],
        output: dict[str, object],
        checkpoint_key: str,
        event_inputs: Mapping[str, object],
    ) -> tuple[ExercisePlanRun, dict[str, object]]:
        output = cast(dict[str, object], _json_for_storage(output))
        output["versions"] = {
            "inputHash": planning_input_hash(payload),
            "exercise": self._definition.version,
            "definitionDigest": self._definition_digest,
            "graph": self._definition.graph_version,
            "sources": payload["sourceVersions"],
            "objective": payload["objective"],
            "algorithm": payload["algorithm"],
            "riskVersion": "not-applicable",
            "riskReason": "task planning consumes no risk model",
        }
        stored = await self._repository.store_plan(
            session_id=session.id,
            checkpoint_key=checkpoint_key,
            input_hash=planning_input_hash(payload),
            input_data=payload,
            output_data=output,
            versions={
                "exercise": self._definition.version,
                "definitionDigest": self._definition_digest,
                "graph": self._definition.graph_version,
                "taskAlgorithm": TASK_ALGORITHM_VERSION,
            },
            idempotency_key_id=claim_id,
        )
        plans = await self._repository.list_plans(session.id)
        visible = next(
            (
                item
                for item in reversed(plans)
                if item.output_data.get("status") in {"FEASIBLE", "OPTIMAL"}
            ),
            None,
        )
        before = _session_state(session)
        session.version += 1
        if event_type == "exercise.override-applied":
            session.consequences["lastPlanId"] = str(stored.id)
        await self._repository.save_session(session)
        projection = await session_projection(
            self._definition,
            self._definition_digest,
            self._repository,
            session,
            self._clock(),
        )
        event = await self._repository.append_event(
            session_id=session.id,
            event_type=event_type,
            actor_callsign=session.callsign,
            display_name=session.display_name,
            expected_session_version=expected_version,
            resulting_session_version=session.version,
            before_state=before,
            after_state=_session_state(session),
            inputs=_event_inputs(
                {
                    **event_inputs,
                    "planId": str(stored.id),
                    "visiblePlanId": None if visible is None else str(visible.id),
                },
                projection,
            ),
            note=None,
        )
        await self._repository.complete_idempotency(
            claim_id=claim_id, response_type="exercise_event", response_id=event.id
        )
        snapshot = event.inputs.get("_responseProjection")
        if not isinstance(snapshot, Mapping):
            raise RuntimeError("exercise planning response snapshot is invalid")
        session.response_projection = freeze_json_object(snapshot)
        return stored, _copy_json_object(snapshot)

    def _payload(
        self,
        checkpoint: MaterializedCheckpoint,
        routes: tuple[TaskCandidateRoute, ...],
        consequences: Mapping[str, object],
        locked: tuple[LockedTaskAssignment, ...] = (),
    ) -> dict[str, object]:
        payload = serialize_planning_input(checkpoint, routes, locked)
        payload["definitionDigest"] = self._definition_digest
        payload["algorithm"] = {
            "taskAlgorithm": TASK_ALGORITHM_VERSION,
            "objectiveWeights": self._definition.objectives[checkpoint.objective].model_dump(
                mode="json", by_alias=True
            ),
            "maxSolverSeconds": 2,
        }
        payload["consequences"] = {
            "corridorCleared": consequences.get("corridorCleared") is True
        }
        return cast(dict[str, object], _json_for_storage(payload))

    async def _replay(
        self, session_id: UUID, event: ExerciseEvent
    ) -> tuple[ExercisePlanRun, dict[str, object]]:
        plan_id = event.inputs.get("planId")
        if not isinstance(plan_id, str):
            raise RuntimeError("plan replay is missing plan ID")
        try:
            stored = await self._repository.get_plan(session_id, UUID(plan_id))
        except ValueError as error:
            raise RuntimeError("plan replay is missing plan ID") from error
        if stored is None:
            raise RuntimeError("plan replay does not exist")
        if (
            stored.versions.get("exercise") != self._definition.version
            or stored.versions.get("definitionDigest") != self._definition_digest
            or stored.versions.get("graph") != self._definition.graph_version
            or stored.versions.get("taskAlgorithm") != TASK_ALGORITHM_VERSION
        ):
            raise RuntimeError("plan replay does not match exercise definition")
        replay_session = _session_from_state(event.after_state)
        _require_definition(replay_session, self._definition, self._definition_digest)
        snapshot = event.inputs.get("_responseProjection")
        _validate_replay_snapshot(snapshot, replay_session, self._definition)
        actionable = stored.output_data.get("status") in {"FEASIBLE", "OPTIMAL"}
        if not isinstance(snapshot, Mapping) or (
            actionable and snapshot.get("latestPlan") != stored.output_data
        ):
            raise RuntimeError("exercise replay response is invalid")
        if not actionable:
            actions = snapshot.get("allowedActions")
            if not isinstance(actions, tuple) or "generate-plan" not in actions:
                raise RuntimeError("exercise replay response is invalid")
            visible_id = event.inputs.get("visiblePlanId")
            if visible_id is None:
                if snapshot.get("latestPlan") is not None:
                    raise RuntimeError("exercise replay response is invalid")
            elif isinstance(visible_id, str):
                try:
                    visible = await self._repository.get_plan(session_id, UUID(visible_id))
                except ValueError as error:
                    raise RuntimeError("exercise replay response is invalid") from error
                plans = await self._repository.list_plans(session_id)
                if (
                    visible is None
                    or visible.output_data.get("status") not in {"FEASIBLE", "OPTIMAL"}
                    or visible.id not in [item.id for item in plans[: plans.index(stored)]]
                    or snapshot.get("latestPlan") != visible.output_data
                ):
                    raise RuntimeError("exercise replay response is invalid")
            else:
                raise RuntimeError("exercise replay response is invalid")
        return stored, _copy_json_object(snapshot)
