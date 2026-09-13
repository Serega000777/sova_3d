from fastapi import APIRouter

from app.api import formats, uploads

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(formats.router)
api_v1.include_router(uploads.router)
