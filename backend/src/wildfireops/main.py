from fastapi import FastAPI

from wildfireops.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="WildfireOps")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved.app_name}

    return app


app = create_app()
