import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.types import Message, Scope

from wildfireops.api.dependencies import (
    get_decision_service,
    get_recommendation_service,
    get_scenario_service,
)
from wildfireops.api.routes.decisions import router as decisions_router
from wildfireops.api.routes.scenarios import router as scenarios_router
from wildfireops.decision.commands import StoredDecision


class _DecisionService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def decide(self, *_args: object) -> StoredDecision:
        self._events.append("endpoint")
        return StoredDecision(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            recommendation_id=UUID("00000000-0000-0000-0000-000000000002"),
            action="reject",
            note="Do not dispatch",
            actor_id="demo-operator",
            assignments=(),
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_decision_dependency_commits_before_response_start() -> None:
    events: list[str] = []
    app = FastAPI()
    app.include_router(decisions_router)

    async def dependency() -> AsyncIterator[_DecisionService]:
        events.append("dependency-enter")
        try:
            yield _DecisionService(events)
        finally:
            events.append("commit")

    app.dependency_overrides[get_decision_service] = dependency
    body = json.dumps(
        {"action": "reject", "note": "Do not dispatch", "editedAssignments": []}
    ).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/recommendations/00000000-0000-0000-0000-000000000002/decisions",
        "raw_path": b"/api/recommendations/00000000-0000-0000-0000-000000000002/decisions",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"idempotency-key", b"decision-key"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "state": {},
    }
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            events.append("response-start")

    await app(scope, receive, send)

    assert events == ["dependency-enter", "endpoint", "commit", "response-start"]


@pytest.mark.parametrize(
    ("router", "path", "provider"),
    [
        (scenarios_router, "/api/incidents/{incident_id}/scenarios", get_scenario_service),
        (scenarios_router, "/api/scenarios/{scenario_id}/versions", get_scenario_service),
        (
            scenarios_router,
            "/api/scenario-versions/{version_id}/recommendations",
            get_recommendation_service,
        ),
        (
            decisions_router,
            "/api/recommendations/{recommendation_id}/decisions",
            get_decision_service,
        ),
    ],
)
def test_write_routes_close_dependencies_before_response(
    router: object,
    path: str,
    provider: object,
) -> None:
    routes = getattr(router, "routes")
    route = next(
        candidate
        for candidate in routes
        if isinstance(candidate, APIRoute) and candidate.path == path
    )
    dependency = next(
        candidate for candidate in route.dependant.dependencies if candidate.call is provider
    )

    assert dependency.scope == "function"
