from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID

from wildfireops.decision.recommendations import StoredRecommendationAssignment
from wildfireops.domain.scenario_versions import IdempotencyClaim


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    action: Literal["approve", "reject", "edit"]
    note: str
    edited_assignments: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionRecommendation:
    id: UUID
    scenario_version_id: UUID
    incident_snapshot_id: UUID
    input_version: str
    source_versions: Mapping[str, object]
    graph_version: str
    risk_version: str
    algorithm_version: str
    solver_status: str
    request_inputs: Mapping[str, object]
    proposals: tuple[StoredRecommendationAssignment, ...]
    terminal_decision_id: UUID | None


@dataclass(frozen=True, slots=True)
class ValidatedDecision:
    recommendation: DecisionRecommendation
    action: Literal["approve", "reject", "edit"]
    note: str
    assignments: tuple[StoredRecommendationAssignment, ...]


@dataclass(frozen=True, slots=True)
class StoredDecision:
    id: UUID
    recommendation_id: UUID
    action: str
    note: str
    actor_id: str
    assignments: tuple[StoredRecommendationAssignment, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    decision_action_id: UUID
    actor_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    before_state: Mapping[str, object]
    after_state: Mapping[str, object]
    inputs: Mapping[str, object]
    occurred_at: datetime


class DecisionRepository(Protocol):
    async def claim_idempotency(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyClaim: ...

    async def complete_idempotency(
        self,
        *,
        claim_id: UUID,
        response_type: str,
        response_id: UUID,
    ) -> None: ...

    async def lock_recommendation(
        self,
        recommendation_id: UUID,
    ) -> DecisionRecommendation | None: ...

    async def acquire_incident_refresh_lock(self) -> None: ...

    async def current_input_version(
        self,
        recommendation: DecisionRecommendation,
    ) -> str | None: ...

    async def lock_resources(
        self,
        resource_ids: tuple[str, ...],
    ) -> frozenset[str]: ...

    async def store_decision(
        self,
        validated: ValidatedDecision,
        actor_id: str,
        idempotency_key_id: UUID,
    ) -> UUID: ...

    async def store_assignments_if_approved(
        self,
        validated: ValidatedDecision,
        decision_id: UUID,
    ) -> None: ...

    async def append_audit_event(
        self,
        validated: ValidatedDecision,
        actor_id: str,
        decision_id: UUID,
    ) -> None: ...

    async def get_decision(self, decision_id: UUID) -> StoredDecision | None: ...


class AuditRepository(Protocol):
    async def list_events(
        self,
        recommendation_id: UUID | None,
    ) -> tuple[AuditEvent, ...]: ...

    async def get_event(self, event_id: UUID) -> AuditEvent | None: ...


class DecisionError(ValueError):
    """Base class for transport-neutral decision failures."""


class RecommendationNotFound(DecisionError):
    code = "recommendation_not_found"


class DecisionValidationError(DecisionError):
    code = "decision_invalid"


class DecisionIdempotencyConflict(DecisionError):
    code = "idempotency_conflict"


class RecommendationAlreadyDecided(DecisionError):
    code = "recommendation_already_decided"


class RecommendationNotActionable(DecisionError):
    code = "recommendation_not_actionable"


class RecommendationStale(DecisionError):
    code = "recommendation_stale"


class ResourceAlreadyAssigned(DecisionError):
    code = "resource_already_assigned"


class AuditEventNotFound(DecisionError):
    code = "audit_event_not_found"


class DecisionCommandService:
    def __init__(self, repository: DecisionRepository) -> None:
        self._repository = repository

    async def decide(
        self,
        recommendation_id: str,
        request: DecisionRequest,
        actor_id: str,
        idempotency_key: str,
    ) -> StoredDecision:
        parsed_id = _identifier(recommendation_id, RecommendationNotFound)
        normalized = _normalize_request(request)
        actor = _nonblank(actor_id, "actor_id")
        key = _nonblank(idempotency_key, "idempotency_key")
        request_hash = _request_hash(
            {
                "action": normalized.action,
                "note": normalized.note,
                "edited_assignments": [
                    list(item) for item in normalized.edited_assignments
                ],
                "actor_id": actor,
            }
        )
        claim = await self._repository.claim_idempotency(
            scope=f"recommendation:{parsed_id}:decision",
            key=key,
            request_hash=request_hash,
        )
        if not claim.created:
            if claim.request_hash != request_hash:
                raise DecisionIdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            if claim.response_type != "decision" or claim.response_id is None:
                raise RuntimeError("idempotency response is incomplete")
            replayed = await self._repository.get_decision(claim.response_id)
            if replayed is None:
                raise RuntimeError("idempotency response does not exist")
            return replayed

        recommendation = await self._repository.lock_recommendation(parsed_id)
        if recommendation is None:
            raise RecommendationNotFound("recommendation was not found")
        if recommendation.terminal_decision_id is not None:
            raise RecommendationAlreadyDecided("recommendation is already decided")
        if normalized.action != "reject":
            await self._repository.acquire_incident_refresh_lock()
            current_input_version = await self._repository.current_input_version(
                recommendation
            )
            if current_input_version != recommendation.input_version:
                raise RecommendationStale("recommendation inputs are no longer current")
        validated = _validate_decision(recommendation, normalized)
        if validated.assignments:
            resource_ids = tuple(
                sorted(item.resource_id for item in validated.assignments)
            )
            conflicts = await self._repository.lock_resources(resource_ids)
            if conflicts:
                raise ResourceAlreadyAssigned(
                    f"resource is already assigned: {sorted(conflicts)[0]}"
                )
        decision_id = await self._repository.store_decision(
            validated,
            actor,
            claim.id,
        )
        await self._repository.store_assignments_if_approved(validated, decision_id)
        await self._repository.append_audit_event(validated, actor, decision_id)
        await self._repository.complete_idempotency(
            claim_id=claim.id,
            response_type="decision",
            response_id=decision_id,
        )
        stored = await self._repository.get_decision(decision_id)
        if stored is None:
            raise RuntimeError("created decision could not be loaded")
        return stored


class AuditQueryService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def list_events(
        self, recommendation_id: str | None
    ) -> tuple[AuditEvent, ...]:
        parsed = (
            None
            if recommendation_id is None
            else _identifier(recommendation_id, RecommendationNotFound)
        )
        return await self._repository.list_events(parsed)

    async def get_event(self, event_id: str) -> AuditEvent:
        parsed = _identifier(event_id, AuditEventNotFound)
        event = await self._repository.get_event(parsed)
        if event is None:
            raise AuditEventNotFound("audit event was not found")
        return event


def _normalize_request(request: object) -> DecisionRequest:
    if not isinstance(request, DecisionRequest):
        raise DecisionValidationError("decision request is invalid")
    if request.action not in {"approve", "reject", "edit"}:
        raise DecisionValidationError("decision action is invalid")
    note = _nonblank(request.note, "note")
    if len(note) > 2_000:
        raise DecisionValidationError("note must not exceed 2000 characters")
    if not isinstance(request.edited_assignments, tuple):
        raise DecisionValidationError("edited_assignments must be a tuple")
    pairs = tuple(
        (
            _nonblank(resource_id, "resource_id"),
            _nonblank(destination_id, "destination_id"),
        )
        for resource_id, destination_id in request.edited_assignments
    )
    return DecisionRequest(request.action, note, tuple(sorted(pairs)))


def _validate_decision(
    recommendation: DecisionRecommendation,
    request: DecisionRequest,
) -> ValidatedDecision:
    if request.action == "reject":
        if request.edited_assignments:
            raise DecisionValidationError("reject does not accept edited assignments")
        return ValidatedDecision(recommendation, "reject", request.note, ())
    if recommendation.solver_status not in {"FEASIBLE", "OPTIMAL"}:
        raise RecommendationNotActionable("recommendation is not actionable")
    if request.action == "approve":
        if request.edited_assignments:
            raise DecisionValidationError("approve does not accept edited assignments")
        return ValidatedDecision(
            recommendation=recommendation,
            action="approve",
            note=request.note,
            assignments=recommendation.proposals,
        )
    if not request.edited_assignments:
        raise DecisionValidationError("edit requires at least one assignment")
    if len(set(request.edited_assignments)) != len(request.edited_assignments):
        raise DecisionValidationError("edit assignments must be unique")
    resource_ids = [resource_id for resource_id, _ in request.edited_assignments]
    if len(set(resource_ids)) != len(resource_ids):
        raise DecisionValidationError(
            "a resource may be assigned to at most one destination"
        )
    assignments = _edited_assignments(recommendation, request.edited_assignments)
    return ValidatedDecision(recommendation, "edit", request.note, assignments)


def _edited_assignments(
    recommendation: DecisionRecommendation,
    pairs: tuple[tuple[str, str], ...],
) -> tuple[StoredRecommendationAssignment, ...]:
    inputs = recommendation.request_inputs
    resources_raw = inputs.get("resources")
    demands_raw = inputs.get("demands")
    routes_raw = inputs.get("candidate_routes")
    limits = inputs.get("limits")
    overlays = inputs.get("overlays")
    if (
        not isinstance(resources_raw, list)
        or not isinstance(demands_raw, list)
        or not isinstance(routes_raw, list)
    ):
        raise DecisionValidationError("recommendation inputs are invalid")
    if not isinstance(limits, Mapping) or not isinstance(overlays, Mapping):
        raise DecisionValidationError("recommendation inputs are invalid")
    resources = {
        str(item.get("resource_id")): item
        for item in resources_raw
        if isinstance(item, Mapping)
    }
    demands = {
        str(item.get("destination_id")): item
        for item in demands_raw
        if isinstance(item, Mapping)
    }
    routes = {
        (str(item.get("resource_id")), str(item.get("destination_id"))): item.get(
            "route"
        )
        for item in routes_raw
        if isinstance(item, Mapping)
    }
    max_response = limits.get("max_response_minutes")
    closed_edges = overlays.get("closed_edge_ids")
    if (
        isinstance(max_response, bool)
        or not isinstance(max_response, int)
        or not isinstance(closed_edges, list)
    ):
        raise DecisionValidationError("recommendation inputs are invalid")
    expected_closure_hash = sha256(
        json.dumps(
            sorted(str(item) for item in closed_edges),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assignments: list[StoredRecommendationAssignment] = []
    capacity_by_destination: dict[str, int] = {}
    for resource_id, destination_id in pairs:
        resource = resources.get(resource_id)
        demand = demands.get(destination_id)
        route = routes.get((resource_id, destination_id))
        if resource is None or demand is None or not isinstance(route, Mapping):
            raise DecisionValidationError("edited assignment is not a candidate pair")
        available = resource.get("available")
        capabilities = resource.get("capabilities")
        required_capability = demand.get("required_capability")
        capacity = resource.get("capacity")
        if available is not True:
            raise DecisionValidationError(f"resource is unavailable: {resource_id}")
        if (
            not isinstance(capabilities, list)
            or not isinstance(required_capability, str)
            or required_capability not in capabilities
        ):
            raise DecisionValidationError(
                f"resource is incompatible with destination: {resource_id} -> {destination_id}"
            )
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise DecisionValidationError("recommendation resource capacity is invalid")
        status = route.get("status")
        travel_minutes = route.get("travel_minutes")
        if status != "reachable":
            raise DecisionValidationError(
                f"route is unreachable: {resource_id} -> {destination_id}"
            )
        if route.get("closure_hash") != expected_closure_hash:
            raise DecisionValidationError("candidate route closure hash is invalid")
        if (
            isinstance(travel_minutes, bool)
            or not isinstance(travel_minutes, int | float)
            or travel_minutes > max_response
        ):
            raise DecisionValidationError(
                f"response time exceeds limit: {resource_id} -> {destination_id}"
            )
        assignments.append(
            StoredRecommendationAssignment(
                resource_id=resource_id,
                destination_id=destination_id,
                route=dict(route),
                travel_minutes=float(travel_minutes),
                capacity=capacity,
            )
        )
        capacity_by_destination[destination_id] = (
            capacity_by_destination.get(destination_id, 0) + capacity
        )
    for destination_id, capacity in capacity_by_destination.items():
        required = demands[destination_id].get("required_capacity")
        if isinstance(required, bool) or not isinstance(required, int) or required <= 0:
            raise DecisionValidationError("recommendation demand capacity is invalid")
        if capacity < required:
            raise DecisionValidationError(
                f"capacity for {destination_id} is below required capacity {required}"
            )
    return tuple(assignments)


def _identifier(value: object, error_type: type[DecisionError]) -> UUID:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        raise error_type("resource was not found") from None


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionValidationError(f"{field} must be a nonblank string")
    return value.strip()


def _request_hash(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
