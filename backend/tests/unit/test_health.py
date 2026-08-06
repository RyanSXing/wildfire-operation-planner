import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wildfireops.api.event_bus import EventBus
from wildfireops.config import Settings
from wildfireops.main import create_app
from wildfireops.replay.loader import ReplayLoader


PARK_FIRE_PACKAGE = Path(__file__).parents[3] / "data/replay/park-fire"


def test_health_reports_service_name() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wildfireops-api"}


def test_replay_startup_uses_manifest_clock_and_graph() -> None:
    app = create_app(Settings(replay_package=PARK_FIRE_PACKAGE))
    loader = ReplayLoader(PARK_FIRE_PACKAGE)

    assert app.state.clock() == loader.manifest.end_at
    assert loader.manifest.road_graph is not None
    assert tuple(app.state.graphs) == (loader.manifest.road_graph.graph_version,)


def test_replay_startup_validates_loaded_exercise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wildfireops import main

    observed: list[tuple[object, object]] = []
    monkeypatch.setattr(
        main,
        "validate_exercise_runtime",
        lambda definition, graph: observed.append((definition, graph)),
    )

    app = main.create_app(Settings(replay_package=PARK_FIRE_PACKAGE))

    assert len(observed) == 1
    assert observed[0][0] is app.state.exercise_definition
    assert observed[0][1] is next(iter(app.state.graphs.values()))


def test_live_startup_keeps_wall_clock_and_no_graphs() -> None:
    app = create_app(Settings(replay_package=None))

    assert app.state.graphs == {}


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
