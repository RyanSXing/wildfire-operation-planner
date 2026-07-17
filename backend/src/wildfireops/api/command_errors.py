from wildfireops.api.errors import ApiError
from wildfireops.decision.commands import (
    AuditEventNotFound,
    DecisionError,
    DecisionIdempotencyConflict,
    DecisionValidationError,
    RecommendationAlreadyDecided,
    RecommendationNotActionable,
    RecommendationNotFound,
    RecommendationStale,
    ResourceAlreadyAssigned,
)
from wildfireops.decision.recommendations import (
    RecommendationError,
    RecommendationIdempotencyConflict,
    RecommendationInputsInvalid,
    RecommendationNotFound as ScenarioVersionNotFound,
    RecommendationScenarioStale,
)
from wildfireops.decision.scenarios import (
    IdempotencyConflict,
    ScenarioError,
    ScenarioNotFound,
    ScenarioValidationError,
)


def command_api_error(
    error: ScenarioError | RecommendationError | DecisionError,
) -> ApiError:
    if isinstance(
        error,
        (
            ScenarioNotFound,
            ScenarioVersionNotFound,
            RecommendationNotFound,
            AuditEventNotFound,
        ),
    ):
        return ApiError(
            status_code=404,
            code=error.code,
            message=str(error),
        )
    if isinstance(
        error,
        (ScenarioValidationError, RecommendationInputsInvalid, DecisionValidationError),
    ):
        return ApiError(
            status_code=422,
            code=error.code,
            message=str(error),
        )
    if isinstance(
        error,
        (
            IdempotencyConflict,
            RecommendationIdempotencyConflict,
            RecommendationScenarioStale,
            DecisionIdempotencyConflict,
            RecommendationAlreadyDecided,
            RecommendationNotActionable,
            RecommendationStale,
            ResourceAlreadyAssigned,
        ),
    ):
        return ApiError(
            status_code=409,
            code=error.code,
            message=str(error),
        )
    return ApiError(
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
