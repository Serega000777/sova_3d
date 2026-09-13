import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.api.errors import install_error_handlers
from app.api.router import api_v1
from app.config import Settings, load_settings
from app.db import make_engine, make_session_factory
from app.storage import ObjectStorage, S3Storage

API_TITLE = "Physical AI 3D API"
API_VERSION = "0.1.0"


def create_app(settings: Settings | None = None, storage: ObjectStorage | None = None) -> FastAPI:
    """App factory. Run with `uvicorn app.main:create_app --factory`."""
    settings = settings or load_settings()
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.storage = storage or S3Storage(settings)

    @app.middleware("http")
    async def trace_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.trace_id
        return response

    install_error_handlers(app)
    app.include_router(api_v1)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    return app
