"""Painting a model (T-106/T-107, F-034): colour per face, kept with the geometry.

Colour is not geometry: a painted model is the same shape, so painting never touches the
mesh — it assigns a colour to the faces the user swept over and writes a format that can
carry it (GLB for viewing, PLY and 3MF for handing on). The strokes themselves are kept, so
a paint layer can be replayed onto a later version of the same part.

The region shapes mirror `app/geometry/region.py` deliberately: the worker stays standalone
(it never imports the API), and a test holds the two shapes to the same JSON.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field, model_validator

from worker.importers.common import as_single_mesh

Axis = Literal["x", "y", "z"]
AXES: tuple[Axis, ...] = ("x", "y", "z")
DEFAULT_COLOUR = "#c9ced8"
# What can actually carry the paint out of here. PLY keeps a colour per face exactly; glTF
# and OBJ store colour per vertex, so a stroke's edge blends across one triangle. 3MF is not
# on this list because the writer we use drops colour — claiming it would be a lie.
COLOUR_FORMATS = frozenset({"glb", "ply", "obj"})
EXACT_COLOUR_FORMATS = frozenset({"ply"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoxRegion(Strict):
    kind: Literal["box"] = "box"
    min_mm: tuple[float, float, float]
    max_mm: tuple[float, float, float]


class LassoRegion(Strict):
    kind: Literal["lasso"] = "lasso"
    axis: Axis
    offset_mm: float
    depth_mm: Annotated[float, Field(gt=0)] = 10.0
    points_mm: list[tuple[float, float]] = Field(min_length=3)


Region = Annotated[BoxRegion | LassoRegion, Field(discriminator="kind")]


class Stroke(Strict):
    """One swipe of colour. Without a region it paints the whole body."""

    colour: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
    region: Region | None = None


class PaintRequest(Strict):
    base_colour: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] = DEFAULT_COLOUR
    strokes: list[Stroke] = Field(default_factory=list, max_length=512)

    @model_validator(mode="after")
    def _has_work(self) -> PaintRequest:
        if not self.strokes and self.base_colour == DEFAULT_COLOUR:
            raise ValueError("nothing to paint: give a stroke or a base colour")
        return self


class PaintResult(BaseModel):
    ok: bool
    faces: int = 0
    faces_before: int = 0
    painted_faces: int = 0
    colours: list[str] = Field(default_factory=list)
    unused_strokes: list[int] = Field(default_factory=list)
    subdivided: bool = False
    message: str | None = None


def rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _inside_box(centres: np.ndarray, region: BoxRegion) -> np.ndarray:
    low = np.asarray(region.min_mm, dtype=float)
    high = np.asarray(region.max_mm, dtype=float)
    return np.all((centres >= low - 1e-6) & (centres <= high + 1e-6), axis=1)


def _inside_lasso(centres: np.ndarray, region: LassoRegion) -> np.ndarray:
    """Point-in-polygon on the plane the outline was drawn on, within its depth."""
    index = AXES.index(region.axis)
    plane = [i for i in range(3) if i != index]
    half = region.depth_mm / 2
    within_depth = np.abs(centres[:, index] - region.offset_mm) <= half + 1e-6

    polygon = np.asarray(region.points_mm, dtype=float)
    x = centres[:, plane[0]]
    y = centres[:, plane[1]]
    inside = np.zeros(len(centres), dtype=bool)
    count = len(polygon)
    for i in range(count):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % count]
        crosses = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            boundary = x0 + (y - y0) / np.where(y1 == y0, np.nan, y1 - y0) * (x1 - x0)
        hit = crosses & (x < np.nan_to_num(boundary, nan=-np.inf))
        inside ^= hit
    return inside & within_depth


# A stroke can be much smaller than the triangles under it (a box has two per face), so the
# mesh is refined until a triangle is small enough for the outline to mean something. The
# shape does not change — only how finely it is tessellated — and the printable model is a
# separate asset that is never touched.
MAX_PAINT_FACES = 60_000


def inside_region(points: np.ndarray, region: Region) -> np.ndarray:
    """Which of `points` (n × 3, mm) a region covers — shared with the engineering facts."""
    if isinstance(region, BoxRegion):
        return _inside_box(points, region)
    return _inside_lasso(points, region)


def _bounds(region: Region) -> tuple[np.ndarray, np.ndarray]:
    """The axis-aligned box a region can touch, in mm."""
    if isinstance(region, BoxRegion):
        return np.asarray(region.min_mm, dtype=float), np.asarray(region.max_mm, dtype=float)
    index = AXES.index(region.axis)
    plane = [i for i in range(3) if i != index]
    points = np.asarray(region.points_mm, dtype=float)
    low = np.zeros(3)
    high = np.zeros(3)
    low[plane], high[plane] = points.min(axis=0), points.max(axis=0)
    low[index] = region.offset_mm - region.depth_mm / 2
    high[index] = region.offset_mm + region.depth_mm / 2
    return low, high


def _brush_size(region: Region) -> float:
    """How fine a stroke is: the smallest span you can see."""
    if isinstance(region, BoxRegion):
        # The brush is what you see, not how thin the slab is: ignore the smallest span.
        spans = sorted(hi - lo for lo, hi in zip(region.min_mm, region.max_mm, strict=True))
        visible = [span for span in spans[1:] if span > 0] or [s for s in spans if s > 0]
        return min(visible) if visible else 0.0
    points = np.asarray(region.points_mm, dtype=float)
    spans = (points.max(axis=0) - points.min(axis=0)).tolist()
    positive = [span for span in spans if span > 0]
    return min(positive) if positive else 0.0


def _refine_for(mesh: trimesh.Trimesh, request: PaintRequest) -> tuple[trimesh.Trimesh, bool]:
    """Split the triangles a stroke's edge runs through until they are finer than the stroke.

    Only those triangles: the inside of a stroke and the untouched rest of the model stay
    as they were, so a painted preview stays small. Splitting one triangle leaves a
    T-junction on its neighbours, which is harmless for a preview and never reaches the
    printable model.
    """
    regions = [stroke.region for stroke in request.strokes if stroke.region is not None]
    sizes = [size for size in (_brush_size(region) for region in regions) if size > 0]
    if not sizes:
        return mesh, False
    # Six triangles across the finest stroke keep its edge from looking like a saw.
    target = max(min(sizes) / 6.0, 0.05)
    subdivided = False
    for _ in range(10):
        vertices = mesh.vertices
        faces = mesh.faces
        corners = vertices[faces]  # (n, 3, 3)
        longest = np.linalg.norm(corners - np.roll(corners, -1, axis=1), axis=2).max(axis=1)
        big = longest > target
        if not big.any():
            break
        wanted = np.zeros(len(faces), dtype=bool)
        face_low = corners.min(axis=1)
        face_high = corners.max(axis=1)
        for region in regions:
            inside = inside_region(vertices, region)[faces]  # (n, 3): which corners are in
            straddles = inside.any(axis=1) & ~inside.all(axis=1)
            low, high = _bounds(region)
            # A stroke smaller than the triangle has no corner inside it: catch it by its box.
            overlaps = np.all((face_high >= low) & (face_low <= high), axis=1)
            wanted |= straddles | (overlaps & ~inside.all(axis=1))
        pick = np.flatnonzero(big & wanted)
        if pick.size == 0 or len(faces) + 3 * pick.size > MAX_PAINT_FACES:
            break  # done, or the face budget is spent
        mesh = mesh.subdivide(face_index=pick)
        subdivided = True
    if subdivided:
        # A fresh mesh: per-face attributes from the old tessellation must not follow along.
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
    return mesh, subdivided


def paint_mesh(mesh: trimesh.Trimesh, request: PaintRequest) -> PaintResult:
    """Colour a mesh; the caller keeps its own reference (see paint_mesh_into)."""
    return paint_mesh_into(mesh, request)[0]


def paint_mesh_into(
    mesh: trimesh.Trimesh, request: PaintRequest
) -> tuple[PaintResult, trimesh.Trimesh]:
    """Colour the faces each stroke covers. The shape is untouched; only colour is added."""
    before = len(mesh.faces)
    if before == 0:
        return PaintResult(ok=False, message="the model has no faces to paint"), mesh
    mesh, subdivided = _refine_for(mesh, request)
    faces = len(mesh.faces)

    colours = np.tile(np.array([*rgb(request.base_colour), 255], dtype=np.uint8), (faces, 1))
    centres = mesh.triangles_center
    painted = np.zeros(faces, dtype=bool)
    unused: list[int] = []

    for index, stroke in enumerate(request.strokes):
        if stroke.region is None:
            selected = np.ones(faces, dtype=bool)
        elif isinstance(stroke.region, BoxRegion):
            selected = _inside_box(centres, stroke.region)
        else:
            selected = _inside_lasso(centres, stroke.region)
        if not selected.any():
            unused.append(index)  # the user drew somewhere the model is not
            continue
        colours[selected] = [*rgb(stroke.colour), 255]
        painted |= selected

    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, face_colors=colours)
    used = [request.base_colour, *(s.colour for s in request.strokes)]
    return (
        PaintResult(
            ok=True,
            faces=faces,
            faces_before=before,
            painted_faces=int(painted.sum()),
            colours=list(dict.fromkeys(used)),
            unused_strokes=unused,
            subdivided=subdivided,
        ),
        mesh,
    )


def paint_file(
    source: Path, source_format: str, request: PaintRequest, output: Path, target_format: str
) -> PaintResult:
    """Read a mesh, colour it, and write a format that can carry the colours."""
    if target_format not in COLOUR_FORMATS:
        return PaintResult(ok=False, message=f"{target_format} cannot carry colour")
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        return PaintResult(ok=False, message="the file has no mesh to paint")
    mesh = mesh.copy()

    result, mesh = paint_mesh_into(mesh, request)
    if not result.ok:
        return result

    if target_format == "glb":
        scaled = mesh.copy()
        # glTF and OBJ colour vertices, not faces: with shared vertices every stroke edge
        # would smear across the neighbouring triangles. Give each face its own vertices so
        # the colours come out exactly as painted (the mesh is a preview; size is fine).
        scaled.unmerge_vertices()
        scaled.apply_scale(0.001)  # glTF is metres by spec
        payload = trimesh.Scene(scaled).export(file_type="glb")
    elif target_format == "ply":
        payload = mesh.export(file_type="ply", encoding="binary")  # PLY keeps face colours
    else:
        flat = mesh.copy()
        flat.unmerge_vertices()
        payload = flat.export(file_type="obj", include_color=True)
    output.write_bytes(payload if isinstance(payload, bytes) else str(payload).encode())
    return result


def run_in_sandbox(
    source: Path,
    source_format: str,
    request: PaintRequest,
    output: Path,
    target_format: str = "glb",
    limits: Any | None = None,
) -> PaintResult:
    """Paint in the sandboxed child, like every other operation on an uploaded mesh."""
    from worker import sandbox

    outcome = sandbox.run(
        "worker.paint",
        [source_format, target_format, str(source), str(output), request.model_dump_json()],
        input_path=source,
        limits=limits or sandbox.DEFAULT_LIMITS,
    )
    if not outcome.ok:
        return PaintResult(ok=False, message=outcome.message)
    return PaintResult.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: paint <src_fmt> <dst_fmt> <src> <dst> <request-json>
    import json
    import sys

    source_format, target_format, source_path, output_path, payload = sys.argv[1:6]
    try:
        outcome = paint_file(
            Path(source_path),
            source_format,
            PaintRequest.model_validate_json(payload),
            Path(output_path),
            target_format,
        )
        print(json.dumps(outcome.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
