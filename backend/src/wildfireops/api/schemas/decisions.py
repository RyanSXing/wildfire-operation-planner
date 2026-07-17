from datetime import datetime
from typing import Literal

from pydantic import JsonValue

from wildfireops.api.schemas.incidents import ApiModel
from wildfireops.api.schemas.scenarios import RecommendationAssignmentResponse


class EditedAssignmentInput(ApiModel):
    resource_id: str
    destination_id: str


class DecisionCreateRequest(ApiModel):
    action: Literal["approve", "reject", "edit"]
    note: str
    edited_assignments: tuple[EditedAssignmentInput, ...] = ()


class DecisionResponse(ApiModel):
    id: str
    recommendation_id: str
    action: str
    note: str
    actor_id: str
    assignments: tuple[RecommendationAssignmentResponse, ...]
    created_at: datetime


class AuditEventResponse(ApiModel):
    id: str
    decision_action_id: str
    actor_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    scenario_version_id: str
    incident_snapshot_id: str
    recommendation_id: str
    algorithms: dict[str, JsonValue]
    before_state: dict[str, JsonValue]
    after_state: dict[str, JsonValue]
    inputs: dict[str, JsonValue]
    note: str
    occurred_at: datetime


class AuditEventListResponse(ApiModel):
    items: tuple[AuditEventResponse, ...]
