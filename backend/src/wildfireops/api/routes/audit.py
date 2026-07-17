from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic.alias_generators import to_camel

from wildfireops.api.command_errors import command_api_error
from wildfireops.api.dependencies import get_audit_service
from wildfireops.api.schemas.decisions import (
    AuditEventListResponse,
    AuditEventResponse,
)
from wildfireops.decision.commands import AuditEvent, AuditQueryService, DecisionError


router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("", response_model=AuditEventListResponse)
async def list_audit_events(
    service: Annotated[AuditQueryService, Depends(get_audit_service)],
    recommendation_id: Annotated[
        str | None,
        Query(alias="recommendationId"),
    ] = None,
) -> AuditEventListResponse:
    try:
        events = await service.list_events(recommendation_id)
    except DecisionError as error:
        raise command_api_error(error) from error
    return AuditEventListResponse(items=tuple(_response(item) for item in events))


@router.get("/{event_id}", response_model=AuditEventResponse)
async def get_audit_event(
    event_id: str,
    service: Annotated[AuditQueryService, Depends(get_audit_service)],
) -> AuditEventResponse:
    try:
        event = await service.get_event(event_id)
    except DecisionError as error:
        raise command_api_error(error) from error
    return _response(event)


def _response(event: AuditEvent) -> AuditEventResponse:
    inputs = _camel_json(event.inputs)
    before_state = _camel_json(event.before_state)
    after_state = _camel_json(event.after_state)
    assert isinstance(inputs, dict)
    assert isinstance(before_state, dict)
    assert isinstance(after_state, dict)
    algorithms = inputs.get("algorithmVersions")
    return AuditEventResponse(
        id=str(event.id),
        decision_action_id=str(event.decision_action_id),
        actor_id=event.actor_id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=str(event.aggregate_id),
        scenario_version_id=str(inputs["scenarioVersionId"]),
        incident_snapshot_id=str(inputs["incidentSnapshotId"]),
        recommendation_id=str(event.aggregate_id),
        algorithms=algorithms if isinstance(algorithms, dict) else {},
        before_state=before_state,
        after_state=after_state,
        inputs=inputs,
        note=str(after_state["note"]),
        occurred_at=event.occurred_at,
    )


def _camel_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {to_camel(str(key)): _camel_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_camel_json(item) for item in value]
    return value
