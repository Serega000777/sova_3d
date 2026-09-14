from fastapi import APIRouter

from app.api import ai_commands, formats, jobs, projects, uploads

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(formats.router)
api_v1.include_router(uploads.router)
api_v1.include_router(projects.router)
api_v1.include_router(jobs.router)
api_v1.include_router(ai_commands.router)
