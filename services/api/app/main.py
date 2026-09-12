from fastapi import FastAPI

from app.config import Settings, load_settings

API_TITLE = "Physical AI 3D API"
API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or load_settings()
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    return app
