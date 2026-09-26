"""Exports (F-014/F-076): POST /models/{version_id}/exports, GET /assets/{id}/download."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep, StorageDep
from app.api.errors import NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.models.core import WorkspaceRole
from app.models.versioning import Asset
from app.services import jobs, projects
from app.services.assets import (
    REPAIRABLE_FORMATS,
    brep_asset_of,
    model_asset_of,
    preview_asset_of,
)
from app.services.authz import require_workspace_role

router = APIRouter(tags=["exports"])
EXPORT_FORMATS = ("stl", "glb", "3mf", "fbx", "step", "iges")
CAD_FORMATS = ("step", "iges")


class GameExport(BaseModel):
    """F-077: what a game engine gets (the worker validates the same fields again)."""

    name: str = Field(default="Model", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    max_triangles: int = Field(default=20_000, ge=100, le=500_000)
    lod_ratios: list[float] = Field(default_factory=lambda: [0.5, 0.2], max_length=4)
    collider: Literal["convex", "box", "none"] = "convex"
    uv: bool = True
    pivot: Literal["base", "centre", "keep"] = "base"
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    metallic: float = Field(default=0.0, ge=0, le=1)
    roughness: float = Field(default=0.6, ge=0, le=1)
    # a painted version's colours, baked into a texture per LOD
    texture_px: int = Field(default=1024, ge=256, le=4096)


class ExportCreate(BaseModel):
    # STEP/IGES are CAD-ready (F-078): they need the version's B-Rep, not its mesh.
    format: Literal["stl", "glb", "3mf", "fbx", "step", "iges"]
    printable: bool = False
    # F-077: a game-engine GLB (LODs, UVs, material, collider) instead of a plain conversion
    game: GameExport | None = None

    @model_validator(mode="after")
    def _game_is_a_glb(self) -> "ExportCreate":
        if self.game is not None and (self.format != "glb" or self.printable):
            raise ValueError("a game-ready export is a GLB, without the printable gate")
        return self


class DownloadOut(BaseModel):
    asset_id: uuid.UUID
    url: str
    format: str | None
    byte_size: int
    expires_in_seconds: int
    created_at: datetime


@router.post(
    "/models/{version_id}/exports",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_export(
    version_id: uuid.UUID,
    body: ExportCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    if body.format in CAD_FORMATS:
        asset = brep_asset_of(db, version)
        if asset is None:
            raise ValidationFailedError(
                "CAD-ready export needs a B-Rep: this version is a mesh (imported, scanned, "
                "painted or cut). Versions built from operations or imported as CAD have one.",
                {"format": body.format},
            )
    else:
        # F-077: a game asset keeps the paint, and only the painted preview carries it
        painted = preview_asset_of(db, version) if body.game is not None else None
        asset = painted or model_asset_of(db, version)
        if asset is None or asset.format not in REPAIRABLE_FORMATS:
            raise ValidationFailedError("version has no mesh asset to export")
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type="export",
        input={
            "version_id": str(version.id),
            "asset_id": str(asset.id),
            "format": body.format,
            "printable": body.printable,
            "game": body.game.model_dump(mode="json") if body.game else None,
        },
        created_by=principal.user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.get("/assets/{asset_id}/download", response_model=DownloadOut)
def download_asset(
    asset_id: uuid.UUID, db: DbDep, storage: StorageDep, principal: PrincipalDep
) -> DownloadOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError("asset", asset_id)
    require_workspace_role(db, principal.user_id, asset.workspace_id, WorkspaceRole.viewer)
    ttl = 15 * 60
    return DownloadOut(
        asset_id=asset.id,
        url=storage.presign_get(asset.storage_key, ttl_seconds=ttl),
        format=asset.format,
        byte_size=asset.byte_size,
        expires_in_seconds=ttl,
        created_at=asset.created_at,
    )
