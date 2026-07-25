from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import JsonValue

from wildfireops.api.dependencies import (
    get_exercise_planning_service,
    get_exercise_query_service,
    get_exercise_session_service,
)
from wildfireops.api.schemas.exercises import (
    ExerciseAuditResponse,
    ExerciseDebriefResponse,
    ExerciseDecisionRequest,
    ExerciseEventResponse,
    ExerciseMetadataResponse,
    ExercisePlanCommandResponse,
    ExercisePlanResponse,
    ExerciseSessionResponse,
    OverrideRequest,
    SelectObjectiveRequest,
    SessionCommand,
)
from wildfireops.application.exercise_planning import ExercisePlanningService
from wildfireops.application.exercises import (
    ExerciseEvent,
    ExerciseNotFound,
    ExercisePlanRun,
    ExerciseQueryService,
    ExerciseSessionService,
)


router = APIRouter(tags=["exercises"])


@router.get("/api/exercises/{exercise_id}", response_model=ExerciseMetadataResponse)
async def exercise_metadata(
    exercise_id: str,
    service: Annotated[ExerciseQueryService, Depends(get_exercise_query_service)],
) -> ExerciseMetadataResponse:
    return _metadata_response(await service.metadata(exercise_id))


@router.post(
    "/api/exercises/{exercise_id}/sessions",
    response_model=ExerciseSessionResponse,
    status_code=201,
)
async def create_session(
    exercise_id: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExerciseSessionService,
        Depends(get_exercise_session_service, scope="function"),
    ],
) -> ExerciseSessionResponse:
    if exercise_id != service.exercise_id:
        raise ExerciseNotFound("exercise was not found")
    session = await service.create(idempotency_key=idempotency_key)
    return _session_response(await service.project(session))


@router.get(
    "/api/exercise-sessions/{session_id}", response_model=ExerciseSessionResponse
)
async def read_session(
    session_id: UUID,
    service: Annotated[ExerciseQueryService, Depends(get_exercise_query_service)],
) -> ExerciseSessionResponse:
    return _session_response(await service.session(session_id))


@router.post(
    "/api/exercise-sessions/{session_id}/objective",
    response_model=ExerciseSessionResponse,
)
async def select_objective(
    session_id: UUID,
    body: SelectObjectiveRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExerciseSessionService,
        Depends(get_exercise_session_service, scope="function"),
    ],
) -> ExerciseSessionResponse:
    session = await service.select_objective(
        session_id,
        body.objective,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return _session_response(await service.project(session))


@router.post(
    "/api/exercise-sessions/{session_id}/plans",
    response_model=ExercisePlanCommandResponse,
    status_code=201,
)
async def generate_plan(
    session_id: UUID,
    body: SessionCommand,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExercisePlanningService,
        Depends(get_exercise_planning_service, scope="function"),
    ],
) -> ExercisePlanCommandResponse:
    plan, session = await service.generate_plan(
        session_id,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return _plan_command_response(plan, session)


@router.post(
    "/api/exercise-sessions/{session_id}/advance",
    response_model=ExerciseSessionResponse,
)
async def advance(
    session_id: UUID,
    body: SessionCommand,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExerciseSessionService,
        Depends(get_exercise_session_service, scope="function"),
    ],
) -> ExerciseSessionResponse:
    session = await service.advance(
        session_id,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return _session_response(await service.project(session))


@router.post(
    "/api/exercise-sessions/{session_id}/overrides",
    response_model=ExercisePlanCommandResponse,
    status_code=201,
)
async def apply_override(
    session_id: UUID,
    body: OverrideRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExercisePlanningService,
        Depends(get_exercise_planning_service, scope="function"),
    ],
) -> ExercisePlanCommandResponse:
    plan, session = await service.apply_override(
        session_id,
        resource_id=body.resource_id,
        task_id=body.task_id,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return _plan_command_response(plan, session)


@router.post(
    "/api/exercise-sessions/{session_id}/decisions",
    response_model=ExerciseSessionResponse,
    status_code=201,
)
async def decide(
    session_id: UUID,
    body: ExerciseDecisionRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        ExerciseSessionService,
        Depends(get_exercise_session_service, scope="function"),
    ],
) -> ExerciseSessionResponse:
    session = await service.decide(
        session_id,
        display_name=body.display_name,
        note=body.note,
        expected_version=body.expected_version,
        idempotency_key=idempotency_key,
    )
    return _session_response(await service.project(session))


@router.get("/api/exercise-sessions/{session_id}/audit", response_model=ExerciseAuditResponse)
async def audit(
    session_id: UUID,
    service: Annotated[ExerciseQueryService, Depends(get_exercise_query_service)],
) -> ExerciseAuditResponse:
    return ExerciseAuditResponse(
        items=tuple(_event_response(item) for item in await service.audit(session_id))
    )


@router.get(
    "/api/exercise-sessions/{session_id}/debrief", response_model=ExerciseDebriefResponse
)
async def debrief(
    session_id: UUID,
    service: Annotated[ExerciseQueryService, Depends(get_exercise_query_service)],
) -> ExerciseDebriefResponse:
    result = await service.debrief(session_id)
    return ExerciseDebriefResponse(
        session=_json_object(result["session"]),
        plans=tuple(_json_object(item) for item in _json_sequence(result["plans"])),
        final_plan=_json_object(result["finalPlan"]),
        events=tuple(_json_object(item) for item in _json_sequence(result["events"])),
    )


def _session_response(state: Mapping[str, object]) -> ExerciseSessionResponse:
    return ExerciseSessionResponse(
        id=_text(state, "id"),
        exercise_id=_text(state, "exerciseId"),
        definition_version=_text(state, "definitionVersion"),
        definition_digest=_text(state, "definitionDigest"),
        callsign=_text(state, "callsign"),
        display_name=_optional_text(state, "displayName"),
        checkpoint_index=_integer(state, "checkpointIndex"),
        objective=_optional_text(state, "objective"),
        status=_text(state, "status"),
        version=_integer(state, "version"),
        consequences=_json_object(state["consequences"]),
        expires_at=_timestamp(state["expiresAt"]),
        allowed_actions=tuple(_text_value(item, "allowedActions") for item in _json_sequence(state["allowedActions"])),
        current_checkpoint=_json_object(state["currentCheckpoint"]),
        latest_plan=(None if state["latestPlan"] is None else _json_object(state["latestPlan"])),
    )


def _metadata_response(value: Mapping[str, object]) -> ExerciseMetadataResponse:
    return ExerciseMetadataResponse(
        exercise_id=_text(value, "exerciseId"),
        version=_text(value, "version"),
        name=_text(value, "name"),
        description=_text(value, "description"),
        checkpoint_count=_integer(value, "checkpointCount"),
        objectives=tuple(_text_value(item, "objectives") for item in _json_sequence(value["objectives"])),
        safety_statement=_text(value, "safetyStatement"),
        assets=tuple(_json_object(item) for item in _json_sequence(value["assets"])),
        resources=tuple(_json_object(item) for item in _json_sequence(value["resources"])),
    )


def _plan_command_response(
    plan: ExercisePlanRun, session: Mapping[str, object]
) -> ExercisePlanCommandResponse:
    return ExercisePlanCommandResponse(session=_session_response(session), plan=_plan_response(plan))


def _plan_response(plan: ExercisePlanRun) -> ExercisePlanResponse:
    return ExercisePlanResponse(
        id=str(plan.id),
        session_id=str(plan.session_id),
        checkpoint_key=plan.checkpoint_key,
        input_hash=plan.input_hash,
        input_data=_json_object(plan.input_data),
        output_data=_json_object(plan.output_data),
        versions=_json_object(plan.versions),
        created_at=plan.created_at,
    )


def _event_response(event: ExerciseEvent) -> ExerciseEventResponse:
    return ExerciseEventResponse(
        id=str(event.id),
        session_id=str(event.session_id),
        event_type=event.event_type,
        actor_callsign=event.actor_callsign,
        display_name=event.display_name,
        expected_session_version=event.expected_session_version,
        resulting_session_version=event.resulting_session_version,
        before_state=_json_object(event.before_state),
        after_state=_json_object(event.after_state),
        inputs=_json_object(event.inputs),
        note=event.note,
        occurred_at=event.occurred_at,
    )


def _json_object(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError("exercise projection must be an object")
    return cast(dict[str, JsonValue], {str(key): _json_value(item) for key, item in value.items()})


def _json_sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("exercise projection must be a sequence")
    return tuple(value)


def _json_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return _json_object(value)
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return cast(JsonValue, value)


def _text(value: Mapping[str, object], key: str) -> str:
    return _text_value(value[key], key)


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    item = value[key]
    return None if item is None else _text_value(item, key)


def _text_value(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"exercise projection {key} must be text")
    return value


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"exercise projection {key} must be an integer")
    return item


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("exercise projection expiresAt must be a timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("exercise projection expiresAt must be a timestamp") from error
