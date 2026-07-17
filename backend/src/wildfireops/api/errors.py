from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wildfireops.application.read_models import ReadModelNotFound


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
