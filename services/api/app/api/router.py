from fastapi import APIRouter

from app.api import (
    ai_commands,
    edits,
    exports,
    formats,
    imports,
    jobs,
    metrics,
    painting,
    printing,
    projects,
    scanning,
    uploads,
)

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(formats.router)
api_v1.include_router(uploads.router)
api_v1.include_router(imports.router)
api_v1.include_router(projects.router)
api_v1.include_router(jobs.router)
api_v1.include_router(ai_commands.router)
api_v1.include_router(edits.router)
api_v1.include_router(scanning.router)
api_v1.include_router(painting.router)
api_v1.include_router(printing.router)
api_v1.include_router(exports.router)
api_v1.include_router(metrics.router)
