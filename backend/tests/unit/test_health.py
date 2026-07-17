import asyncio

import pytest
from fastapi.testclient import TestClient

from wildfireops.api.event_bus import EventBus
from wildfireops.main import create_app


def test_health_reports_service_name() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wildfireops-api"}


@pytest.mark.asyncio
async def test_lifespan_starts_listener_then_cancels_and_awaits_before_dispose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    order: list[str] = []

    async def relay(database_url: str, bus: EventBus) -> None:
        assert database_url.startswith("postgresql+asyncpg://")
        assert bus is app.state.event_bus
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            order.append("relay-stopped")

    app = create_app(event_relay=relay)

    async def dispose(_engine: object) -> None:
        order.append("engine-disposed")

    monkeypatch.setattr(type(app.state.engine), "dispose", dispose)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), timeout=1)

    assert order == ["relay-stopped", "engine-disposed"]


@pytest.mark.asyncio
async def test_lifespan_disposes_engine_after_relay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = asyncio.Event()
    order: list[str] = []

    async def relay(_database_url: str, _bus: EventBus) -> None:
        order.append("relay-failed")
        failed.set()
        raise RuntimeError("synthetic relay failure")

    app = create_app(event_relay=relay)

    async def dispose(_engine: object) -> None:
        order.append("engine-disposed")

    monkeypatch.setattr(type(app.state.engine), "dispose", dispose)
    with pytest.raises(RuntimeError, match="synthetic relay failure"):
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(failed.wait(), timeout=1)

    assert order == ["relay-failed", "engine-disposed"]
