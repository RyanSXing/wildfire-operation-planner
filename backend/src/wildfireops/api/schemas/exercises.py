from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from wildfireops.api.schemas.incidents import ApiModel


class SessionCommand(ApiModel):
    expected_version: int = Field(ge=1)


class SelectObjectiveRequest(SessionCommand):
    objective: Literal[
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    ]


class OverrideRequest(SessionCommand):
    resource_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class ExerciseDecisionRequest(SessionCommand):
    display_name: str | None = Field(default=None, max_length=120)
    note: str = Field(min_length=1, max_length=2000)


class ExerciseSessionResponse(ApiModel):
    id: str
    exercise_id: str
    definition_version: str
    definition_digest: str
    callsign: str
    display_name: str | None
    checkpoint_index: int
    objective: str | None
    status: str
    version: int
    consequences: dict[str, JsonValue]
    expires_at: datetime
    allowed_actions: tuple[str, ...]
    current_checkpoint: dict[str, JsonValue]
    latest_plan: dict[str, JsonValue] | None


class ExerciseMetadataResponse(ApiModel):
    exercise_id: str
    version: str
    name: str
    description: str
    checkpoint_count: int
    objectives: tuple[str, ...]
    safety_statement: str
    assets: tuple[dict[str, JsonValue], ...]
    resources: tuple[dict[str, JsonValue], ...]


class ExercisePlanResponse(ApiModel):
    id: str
    session_id: str
    checkpoint_key: str
    input_hash: str
    input_data: dict[str, JsonValue]
    output_data: dict[str, JsonValue]
    versions: dict[str, JsonValue]
    created_at: datetime


class ExercisePlanCommandResponse(ApiModel):
    session: ExerciseSessionResponse
    plan: ExercisePlanResponse


class ExerciseEventResponse(ApiModel):
    id: str
    session_id: str
    event_type: str
    actor_callsign: str
    display_name: str | None
    expected_session_version: int
    resulting_session_version: int
    before_state: dict[str, JsonValue]
    after_state: dict[str, JsonValue]
    inputs: dict[str, JsonValue]
    note: str | None
    occurred_at: datetime


class ExerciseAuditResponse(ApiModel):
    items: tuple[ExerciseEventResponse, ...]


class ExerciseDebriefResponse(ApiModel):
    session: dict[str, JsonValue]
    plans: tuple[dict[str, JsonValue], ...]
    final_plan: dict[str, JsonValue]
    events: tuple[dict[str, JsonValue], ...]
