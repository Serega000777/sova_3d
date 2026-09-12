from fastapi import FastAPI

API_TITLE = "Physical AI 3D API"
API_VERSION = "0.1.0"


def create_app() -> FastAPI:
    app = FastAPI(title=API_TITLE, version=API_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
