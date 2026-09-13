"""GET /formats — capability matrix and limits (T-016)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import formats

router = APIRouter(tags=["formats"])


class FormatOut(BaseModel):
    id: str
    display_name: str
    extensions: list[str]
    mime_types: list[str]
    representation: formats.Representation
    capabilities: list[formats.Capability]
    max_bytes: int
    notes: str


class FormatsOut(BaseModel):
    formats: list[FormatOut]
    max_upload_bytes: int


@router.get("/formats", response_model=FormatsOut)
def list_formats() -> FormatsOut:
    return FormatsOut(
        formats=[
            FormatOut(
                id=f.id,
                display_name=f.display_name,
                extensions=list(f.extensions),
                mime_types=list(f.mime_types),
                representation=f.representation,
                capabilities=sorted(f.capabilities),
                max_bytes=f.max_bytes,
                notes=f.notes,
            )
            for f in formats.FORMATS.values()
        ],
        max_upload_bytes=formats.MAX_UPLOAD_BYTES,
    )
