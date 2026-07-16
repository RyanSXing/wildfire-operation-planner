from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from wildfireops.api.errors import register_error_handlers
from wildfireops.api.event_bus import EventBus
from wildfireops.api.request_metrics import RequestMetricsMiddleware
from wildfireops.api.routes.events import router as events_router
from wildfireops.api.routes.incidents import router as incidents_router
from wildfireops.api.routes.sources import router as sources_router
from wildfireops.config import Settings, get_settings
from wildfireops.db import create_engine, create_session_factory
from wildfireops.observability import configure_observability


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    engine = create_engine(resolved)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="WildfireOps", lifespan=lifespan)
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.clock = lambda: datetime.now(UTC)
    app.state.event_bus = EventBus()
    app.state.event_heartbeat_seconds = 20.0

    app.add_middleware(RequestMetricsMiddleware)
    register_error_handlers(app)
    app.include_router(incidents_router)
    app.include_router(sources_router)
    app.include_router(events_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved.app_name}

    return app


_runtime_settings = get_settings()
configure_observability(_runtime_settings.environment)
app = create_app(_runtime_settings)
