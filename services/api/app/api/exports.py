"""Exports (F-014/F-076): POST /models/{version_id}/exports, GET /assets/{id}/download."""

import math
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
from app.services import entitlements, jobs, licensing, projects, scenes
from app.services.assets import (
    REPAIRABLE_FORMATS,
    brep_asset_of,
    model_asset_of,
    preview_asset_of,
)
from app.services.authz import require_workspace_role

router = APIRouter(tags=["exports"])
EXPORT_FORMATS = ("stl", "glb", "3mf", "fbx", "usdz", "step", "iges")
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
    format: Literal["stl", "glb", "3mf", "fbx", "usdz", "step", "iges"]
    printable: bool = False
    commercial: bool = False
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


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _joint_animation(
    mechanism: object,
    *,
    kind: str,
    joint_type: str,
    unit: str,
    axes: set[str],
    visible_ids: set[str],
) -> dict[str, object] | None:
    """One trusted joint record as a GLB animation, or None when anything is off."""
    if not isinstance(mechanism, dict) or mechanism.get("kind") != kind:
        return None
    joint = mechanism.get("joint")
    if not isinstance(joint, dict) or joint.get("type") != joint_type:
        return None
    node_id = joint.get("node_id")
    axis = joint.get("axis")
    minimum = _finite(joint.get(f"min_{unit}", 0))
    maximum = _finite(joint.get(f"max_{unit}", 0))
    if (
        axis not in axes
        or not isinstance(node_id, str)
        or node_id not in visible_ids
        or minimum is None
        or maximum is None
        or maximum <= minimum
    ):
        return None
    return {
        "kind": joint_type,
        "node_id": node_id,
        "axis": axis,
        f"min_{unit}": minimum,
        f"max_{unit}": maximum,
        "duration_seconds": 1.0,
    }


def mechanism_animation(
    provenance: dict[str, object], visible_ids: set[str]
) -> dict[str, object] | None:
    """F-038: the single trusted joint of a generated mechanism, for a GLB scene export.

    A hidden or malformed joint yields no animation, and so does a scene carrying both a
    hinge and a sliding lid: one GLB channel must not guess which mechanism is meant.
    """
    candidates = [
        _joint_animation(
            provenance.get("build_hinged_lid"),
            kind="hinged_lid",
            joint_type="revolute",
            unit="angle_deg",
            # The bounded generator creates an X-axis barrel hinge and the Studio preview
            # implements that exact mechanism. Reject forged future axes until both paths
            # support them identically.
            axes={"x"},
            visible_ids=visible_ids,
        ),
        _joint_animation(
            provenance.get("build_sliding_lid"),
            kind="sliding_lid",
            joint_type="prismatic",
            unit="travel_mm",
            # the generator and the Studio preview slide along the lid's +Y guides only
            axes={"y"},
            visible_ids=visible_ids,
        ),
    ]
    present = [key for key in ("build_hinged_lid", "build_sliding_lid") if key in provenance]
    valid = [candidate for candidate in candidates if candidate is not None]
    if len(present) != 1 or len(valid) != 1:
        return None
    return valid[0]


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
    if body.format in CAD_FORMATS:
        entitlements.require(db, principal.user_id, entitlements.Capability.cad_export)
    if body.game is not None:
        entitlements.require(db, principal.user_id, entitlements.Capability.game_export)
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    if body.commercial:
        licensing.assert_may_use_commercially(db, project)
    scene_input: list[dict[str, object]] | None = None
    scene_animation: dict[str, object] | None = None
    explicit_scene = isinstance((version.provenance or {}).get("scene"), dict)
    if explicit_scene:
        if body.format in CAD_FORMATS or body.game is not None:
            raise ValidationFailedError(
                "multi-object scenes currently export as standard mesh STL, 3MF, GLB or FBX; "
                "make an object unique and open it separately for CAD or game-ready export"
            )
        resolved = scenes.resolve_scene(db, version=version, workspace_id=project.workspace_id)
        scene_input = [
            {
                "node_id": node["id"],
                "name": node["name"],
                "asset_id": str(node["resolved_asset_id"]),
                "format": node["format"],
                "world_transform": node["world_transform"],
                "appearance": node.get("appearance"),
            }
            for node in resolved
            if node["kind"] == "object" and node["effective_visible"]
        ]
        if not scene_input:
            raise ValidationFailedError("the scene has no visible geometry to export")
        if body.format == "glb":
            scene_animation = mechanism_animation(
                version.provenance or {}, {str(entry["node_id"]) for entry in scene_input}
            )
    if body.format in CAD_FORMATS:
        asset = brep_asset_of(db, version)
        if asset is None:
            raise ValidationFailedError(
                "CAD-ready export needs a B-Rep: this version is a mesh (imported, scanned, "
                "painted or cut). Versions built from operations or imported as CAD have one.",
                {"format": body.format},
            )
    elif scene_input is not None:
        asset = db.get(Asset, uuid.UUID(str(scene_input[0]["asset_id"])))
        if asset is None:
            raise ValidationFailedError("the scene geometry is unavailable")
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
            "scene": scene_input,
            "scene_animation": scene_animation,
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
