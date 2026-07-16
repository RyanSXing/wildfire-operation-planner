from io import StringIO
import json
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wildfireops.main import create_app
from wildfireops.observability import configure_observability


def _test_app(db_session: AsyncSession) -> FastAPI:
    app = create_app()
    assert db_session.bind is not None
    app.state.session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    return app


@pytest.mark.asyncio
async def test_each_success_and_api_error_emits_one_sanitized_request_metric(
    db_session: AsyncSession,
) -> None:
    output = StringIO()
    configure_observability("production", output=output)
    app = _test_app(db_session)
    missing_id = "00000000-0000-0000-0000-000000000899"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        success = await client.get(
            "/api/health?database_url=secret-db-url",
            headers={
                "X-Request-ID": "request-123",
                "X-API-Key": "secret-api-key",
            },
        )
        missing = await client.get(
            f"/api/incidents/{missing_id}",
            headers={"Authorization": "Bearer secret-access-token"},
        )

    assert success.status_code == 200
    assert success.headers["X-Request-ID"] == "request-123"
    assert missing.status_code == 404
    UUID(missing.headers["X-Request-ID"])

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    request_events = [event for event in events if event["event"] == "api_request"]
    assert len(request_events) == 2
    assert [event["request_id"] for event in request_events] == [
        "request-123",
        missing.headers["X-Request-ID"],
    ]
    assert [event["route"] for event in request_events] == [
        "/api/health",
        "/api/incidents/{incident_id}",
    ]
    assert [event["status_code"] for event in request_events] == [200, 404]
    assert all(event["method"] == "GET" for event in request_events)
    assert all(event["duration_ms"] >= 0 for event in request_events)

    serialized = output.getvalue()
    for secret in (
        "secret-db-url",
        "secret-api-key",
        "secret-access-token",
        "database_url",
        "authorization",
    ):
        assert secret not in serialized.casefold()


@pytest.mark.asyncio
async def test_unhandled_error_emits_one_safe_500_metric_and_request_id(
    db_session: AsyncSession,
) -> None:
    output = StringIO()
    configure_observability("production", output=output)
    app = _test_app(db_session)

    @app.get("/api/test-crash")
    async def crash() -> None:
        raise RuntimeError("secret-database-url-and-api-key")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/test-crash",
            headers={"X-Request-ID": "crash-request"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "crash-request"
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(events) == 1
    assert events[0]["event"] == "api_request"
    assert events[0]["route"] == "/api/test-crash"
    assert events[0]["status_code"] == 500
    assert "secret-database-url-and-api-key" not in output.getvalue()


@pytest.mark.asyncio
async def test_unsafe_request_id_is_replaced_with_a_bounded_uuid(
    db_session: AsyncSession,
) -> None:
    output = StringIO()
    configure_observability("production", output=output)
    app = _test_app(db_session)
    unsafe_id = "x" * 200

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/health",
            headers={"X-Request-ID": unsafe_id},
        )

    generated_id = response.headers["X-Request-ID"]
    UUID(generated_id)
    assert len(generated_id) == 36
    assert unsafe_id not in output.getvalue()
