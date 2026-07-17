from typing import Annotated

from fastapi import APIRouter, Depends, Header

from wildfireops.api.command_errors import command_api_error
from wildfireops.api.dependencies import get_decision_service
from wildfireops.api.routes.scenarios import recommendation_assignment
from wildfireops.api.schemas.decisions import DecisionCreateRequest, DecisionResponse
from wildfireops.decision.commands import (
    DecisionCommandService,
    DecisionError,
    DecisionRequest,
)


router = APIRouter(prefix="/api/recommendations", tags=["decisions"])
_ACTOR_ID = "demo-operator"


@router.post(
    "/{recommendation_id}/decisions",
    response_model=DecisionResponse,
    status_code=201,
)
async def decide_recommendation(
    recommendation_id: str,
    body: DecisionCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[
        DecisionCommandService,
        Depends(get_decision_service, scope="function"),
    ],
) -> DecisionResponse:
    try:
        stored = await service.decide(
            recommendation_id,
            DecisionRequest(
                action=body.action,
                note=body.note,
                edited_assignments=tuple(
                    (item.resource_id, item.destination_id)
                    for item in body.edited_assignments
                ),
            ),
            _ACTOR_ID,
            idempotency_key,
        )
    except DecisionError as error:
        raise command_api_error(error) from error
    return DecisionResponse(
        id=str(stored.id),
        recommendation_id=str(stored.recommendation_id),
        action=stored.action,
        note=stored.note,
        actor_id=stored.actor_id,
        assignments=tuple(
            recommendation_assignment(item) for item in stored.assignments
        ),
        created_at=stored.created_at,
    )
