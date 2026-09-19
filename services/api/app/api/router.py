from fastapi import APIRouter

from app.api import (
    ai_commands,
    edits,
    enclosures,
    engineering,
    exports,
    fit,
    formats,
    imports,
    jobs,
    marketplace,
    metrics,
    painting,
    printing,
    projects,
    scanning,
    signin,
    splitting,
    templates,
    uploads,
)

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(formats.router)
api_v1.include_router(signin.router)
api_v1.include_router(uploads.router)
api_v1.include_router(imports.router)
api_v1.include_router(projects.router)
api_v1.include_router(templates.router)
api_v1.include_router(jobs.router)
api_v1.include_router(ai_commands.router)
api_v1.include_router(edits.router)
api_v1.include_router(engineering.router)
api_v1.include_router(enclosures.router)
api_v1.include_router(fit.router)
api_v1.include_router(splitting.router)
api_v1.include_router(marketplace.router)
api_v1.include_router(scanning.router)
api_v1.include_router(painting.router)
api_v1.include_router(printing.router)
api_v1.include_router(exports.router)
api_v1.include_router(metrics.router)
