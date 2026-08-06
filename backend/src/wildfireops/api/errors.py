from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wildfireops.application.read_models import ReadModelNotFound
from wildfireops.application.exercises import (
    ExerciseError,
    ExerciseTransitionInvalid,
    ExerciseVersionConflict,
)
from wildfireops.api.schemas.exercises import ExerciseSessionResponse


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ExerciseError)
    async def handle_exercise_error(
        request: Request, error: ExerciseError
    ) -> JSONResponse:
        from wildfireops.api.command_errors import exercise_api_error

        return _api_error_response(
            exercise_api_error(
                error,
                current_state=await _exercise_current_state(request, error),
            )
        )

    @app.exception_handler(ReadModelNotFound)
    async def handle_read_model_not_found(
        request: Request,
        error: ReadModelNotFound,
    ) -> JSONResponse:
        del request
        if error.resource == "incident":
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "incident_not_found",
                        "message": "Incident was not found",
                        "details": {"incidentId": error.identifier},
                    }
                },
            )
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": "Resource was not found",
                    "details": {},
                }
            },
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        del request
        return _api_error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request
        fields: list[dict[str, Any]] = []
        for item in error.errors():
            location = [str(part) for part in item.get("loc", ())]
            if location and location[0] == "body":
                location = location[1:]
            fields.append(
                {
                    "field": ".".join(location),
                    "message": item.get("msg", "Invalid value"),
                    "type": item.get("type", "validation_error"),
                }
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"fields": fields},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        del error
        request_id = getattr(request.state, "request_id", None)
        headers = (
            {"X-Request-ID": request_id}
            if isinstance(request_id, str) and request_id
            else None
        )
        return JSONResponse(
            status_code=500,
            headers=headers,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "details": {},
                }
            },
        )


async def _exercise_current_state(
    request: Request, error: ExerciseError
) -> dict[str, object] | None:
    if not isinstance(error, (ExerciseVersionConflict, ExerciseTransitionInvalid)):
        return None
    raw_session_id = request.path_params.get("session_id")
    if not isinstance(raw_session_id, str):
        return None
    try:
        session_id = UUID(raw_session_id)
    except ValueError:
        return None
    provider = request.app.state.command_service_provider
    try:
        async with provider.exercise_queries() as service:
            state = await service.session(session_id)
    except ExerciseError:
        return None
    return ExerciseSessionResponse.model_validate(
        _thaw_json(state)
    ).model_dump(mode="json", by_alias=True)


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    return value


def _api_error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            }
        },
    )
