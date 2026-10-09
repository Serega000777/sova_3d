"""Colour exact-facade mesh faces by stable semantic surface keys.

The keys come from the facade operation plan (wall role, roof role, opening id), never
from transient triangle or OCCT face indices.  Geometry is unchanged; the output is a GLB
preview carrying the selected colours while the exact B-Rep and printable STL stay bare.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field

from worker import sandbox
from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh
from worker.paint import DEFAULT_COLOUR, rgb


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Opening(Strict):
    opening_id: Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,64}$")]
    kind: Literal["window", "door"]
    side: Literal["front", "back", "left", "right"]
    center_mm: float
    width_mm: float
    height_mm: float
    sill_mm: float


class Assignment(Strict):
    surface_key: Annotated[str, Field(pattern=r"^[a-z0-9_.-]{1,160}$")]
    colour: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
    material_id: Annotated[str | None, Field(pattern=r"^[a-z0-9_-]{1,64}$")] = None


class FacadeMaterialRequest(Strict):
    length_mm: Annotated[float, Field(gt=0, le=50_000)]
    width_mm: Annotated[float, Field(gt=0, le=50_000)]
    height_mm: Annotated[float, Field(gt=0, le=18_000)]
    wall_thickness_mm: Annotated[float, Field(gt=0, le=600)]
    roof: Literal["none", "flat", "gable"]
    openings: list[Opening] = Field(default_factory=list, max_length=126)
    assignments: list[Assignment] = Field(default_factory=list, max_length=512)


class FacadeMaterialResult(BaseModel):
    ok: bool
    faces: int = 0
    assigned_faces: int = 0
    applied_surface_keys: list[str] = Field(default_factory=list)
    unused_surface_keys: list[str] = Field(default_factory=list)
    message: str | None = None


def _opening_surface(
    centre: np.ndarray,
    normal: np.ndarray,
    opening: Opening,
    request: FacadeMaterialRequest,
) -> str | None:
    dominant = int(np.argmax(np.abs(normal)))
    top = opening.sill_mm + opening.height_mm
    mid_z = (opening.sill_mm + top) / 2
    tolerance = max(2.5, request.wall_thickness_mm * 0.08)
    prefix = f"opening.{opening.opening_id}"
    if opening.side in ("front", "back"):
        if not (-tolerance <= centre[1] <= request.width_mm + tolerance):
            return None
        low = opening.center_mm - opening.width_mm / 2
        high = opening.center_mm + opening.width_mm / 2
        if not (low - tolerance <= centre[0] <= high + tolerance):
            return None
        if not (opening.sill_mm - tolerance <= centre[2] <= top + tolerance):
            return None
        if dominant == 0:
            return f"{prefix}.left" if centre[0] < opening.center_mm else f"{prefix}.right"
    else:
        if not (-tolerance <= centre[0] <= request.length_mm + tolerance):
            return None
        low = opening.center_mm - opening.width_mm / 2
        high = opening.center_mm + opening.width_mm / 2
        if not (low - tolerance <= centre[1] <= high + tolerance):
            return None
        if not (opening.sill_mm - tolerance <= centre[2] <= top + tolerance):
            return None
        if dominant == 1:
            return f"{prefix}.left" if centre[1] < opening.center_mm else f"{prefix}.right"
    if dominant == 2:
        if opening.kind == "door" and centre[2] < mid_z:
            return None
        return f"{prefix}.sill" if centre[2] < mid_z else f"{prefix}.head"
    return None


def classify_surfaces(mesh: trimesh.Trimesh, request: FacadeMaterialRequest) -> np.ndarray:
    centres = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    keys = np.full(len(centres), "", dtype=object)
    tolerance = max(2.5, request.wall_thickness_mm * 0.08)
    for index, (centre, normal) in enumerate(zip(centres, normals, strict=True)):
        for opening in request.openings:
            key = _opening_surface(centre, normal, opening, request)
            if key is not None:
                keys[index] = key
                break
        if keys[index]:
            continue
        dominant = int(np.argmax(np.abs(normal)))
        if request.roof != "none" and centre[2] >= request.height_mm - tolerance:
            if request.roof == "flat" and dominant == 2:
                keys[index] = "roof.top"
            elif request.roof == "gable" and dominant in (0, 2):
                keys[index] = (
                    "roof.slope.left" if centre[0] <= request.length_mm / 2 else "roof.slope.right"
                )
            if keys[index]:
                continue
        if centre[2] <= request.height_mm + tolerance:
            if dominant == 1 and abs(centre[1]) <= tolerance:
                keys[index] = "wall.front"
            elif dominant == 1 and abs(centre[1] - request.width_mm) <= tolerance:
                keys[index] = "wall.back"
            elif dominant == 0 and abs(centre[0]) <= tolerance:
                keys[index] = "wall.left"
            elif dominant == 0 and abs(centre[0] - request.length_mm) <= tolerance:
                keys[index] = "wall.right"
    return keys


def apply_materials(
    source: Path, request: FacadeMaterialRequest, output: Path
) -> FacadeMaterialResult:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()), file_type="stl", force="mesh", process=False
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        return FacadeMaterialResult(ok=False, message="the facade mesh has no faces")
    keys = classify_surfaces(mesh, request)
    colours = np.tile(np.array([*rgb(DEFAULT_COLOUR), 255], dtype=np.uint8), (len(mesh.faces), 1))
    applied: list[str] = []
    unused: list[str] = []
    assigned = np.zeros(len(mesh.faces), dtype=bool)
    for assignment in request.assignments:
        selected = keys == assignment.surface_key
        if not selected.any():
            unused.append(assignment.surface_key)
            continue
        colours[selected] = [*rgb(assignment.colour), 255]
        assigned |= selected
        applied.append(assignment.surface_key)
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, face_colors=colours)
    mesh.unmerge_vertices()
    mesh.apply_scale(0.001)
    mesh.apply_transform(Z_UP_TO_Y_UP)
    payload = trimesh.Scene(mesh).export(file_type="glb")
    output.write_bytes(payload if isinstance(payload, bytes) else bytes(payload))
    return FacadeMaterialResult(
        ok=True,
        faces=len(mesh.faces),
        assigned_faces=int(assigned.sum()),
        applied_surface_keys=applied,
        unused_surface_keys=unused,
    )


def run_in_sandbox(
    source: Path,
    request: FacadeMaterialRequest,
    output: Path,
) -> FacadeMaterialResult:
    outcome = sandbox.run(
        "worker.facade_materials",
        [str(source), str(output), request.model_dump_json()],
        input_path=source,
        cwd=output.parent,
    )
    if not outcome.ok:
        return FacadeMaterialResult(ok=False, message=outcome.message)
    return FacadeMaterialResult.model_validate(outcome.output)


if __name__ == "__main__":
    import sys

    try:
        result = apply_materials(
            Path(sys.argv[1]),
            FacadeMaterialRequest.model_validate_json(sys.argv[3]),
            Path(sys.argv[2]),
        )
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1) from exc
