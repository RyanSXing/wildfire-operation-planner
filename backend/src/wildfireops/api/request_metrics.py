from collections.abc import Callable, Iterable
import re
from time import perf_counter
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REQUEST_ID_HEADER = b"x-request-id"


class RequestMetricsMiddleware:
    """Emit one bounded, sanitized metric for every HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._app = app
        self._clock = clock
        self._logger = structlog.get_logger("wildfireops.api")

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _resolve_request_id(scope.get("headers", ()))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started_at = self._clock()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", ())
                    if name.lower() != _REQUEST_ID_HEADER
                ]
                headers.append((_REQUEST_ID_HEADER, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            duration_ms = max(0.0, (self._clock() - started_at) * 1_000)
            self._logger.info(
                "api_request",
                request_id=request_id,
                method=scope.get("method", "UNKNOWN"),
                route=_route_template(scope),
                status_code=status_code,
                duration_ms=round(duration_ms, 3),
            )


def _resolve_request_id(headers: Iterable[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() != _REQUEST_ID_HEADER:
            continue
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            break
        if _REQUEST_ID_PATTERN.fullmatch(candidate) is not None:
            return candidate
        break
    return str(uuid4())


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path.startswith("/"):
        return "unmatched"
    root_path = scope.get("root_path", "")
    if not isinstance(root_path, str) or (root_path and not root_path.startswith("/")):
        return "unmatched"
    prefix = root_path.rstrip("/")
    return f"{prefix}{path}"
