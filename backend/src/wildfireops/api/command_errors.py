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
from wildfireops.application.exercises import (
    ExerciseCommandInvalid,
    ExerciseError,
    ExerciseIdempotencyConflict,
    ExerciseNotFound,
    ExerciseSessionExpired,
    ExerciseSessionNotFound,
    ExerciseTransitionInvalid,
    ExerciseVersionConflict,
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


def exercise_api_error(
    error: ExerciseError,
    *,
    current_state: dict[str, object] | None = None,
) -> ApiError:
    if isinstance(error, (ExerciseNotFound, ExerciseSessionNotFound)):
        return ApiError(status_code=404, code=error.code, message=str(error))
    if isinstance(error, ExerciseSessionExpired):
        return ApiError(
            status_code=410,
            code=error.code,
            message=str(error),
            details={"action": "start-new-exercise"},
        )
    if isinstance(
        error,
        (ExerciseVersionConflict, ExerciseTransitionInvalid, ExerciseIdempotencyConflict),
    ):
        return ApiError(
            status_code=409,
            code=error.code,
            message=str(error),
            details=(
                {}
                if current_state is None
                else {
                    "currentSession": current_state,
                    "allowedActions": current_state["allowedActions"],
                }
            ),
        )
    if isinstance(error, ExerciseCommandInvalid):
        return ApiError(
            status_code=422,
            code=error.code,
            message=str(error),
            details=(
                {}
                if not error.fields
                else {
                    "fields": [
                        {"field": field, "message": str(error)}
                        for field in error.fields
                    ]
                }
            ),
        )
    return ApiError(
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
