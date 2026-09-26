"""Game-ready export (F-077): one GLB a game engine can drop in as it is.

What an engine wants and a print file does not carry: metres and +Y up (glTF's own
conventions), the pivot where the object stands (its base centre on the origin), a triangle
budget with lighter LODs for distance, UVs so a material can be textured, a PBR material,
and a simple collision shape instead of the render mesh. Node names follow the conventions
engines key on: `<name>_LOD0..n` (Unity's LOD groups) and `UCX_<name>_00` (Unreal's convex
collision; Godot and Unity users assign it by name).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, field_validator
from trimesh.visual.material import PBRMaterial

from worker.importers.child import parse
from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh, to_platform_axes
from worker.sandbox import SandboxLimits

# Unity refuses convex MeshColliders over 255 triangles; Unreal's UCX hulls are happier small.
MAX_COLLIDER_TRIANGLES = 255
DEVIATION_SAMPLES = 2000
MIN_LOD_TRIANGLES = 64  # below this, fewer triangles only means a wrong shape
GAME_LIMITS = SandboxLimits(wall_seconds=300, cpu_seconds=300, max_output_bytes=128 * 1024**2)


class GameRequest(BaseModel):
    name: str = Field(default="Model", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    max_triangles: int = Field(default=20_000, ge=100, le=500_000)
    # each LOD as a share of LOD0's triangles, heaviest first
    lod_ratios: list[float] = Field(default_factory=lambda: [0.5, 0.2], max_length=4)
    collider: Literal["convex", "box", "none"] = "convex"
    uv: bool = True
    pivot: Literal["base", "centre", "keep"] = "base"
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    metallic: float = Field(default=0.0, ge=0, le=1)
    roughness: float = Field(default=0.6, ge=0, le=1)
    # a painted model's colours, baked into a texture per LOD (needs `uv`)
    texture_px: int = Field(default=1024, ge=256, le=4096)

    @field_validator("lod_ratios")
    @classmethod
    def _descending(cls, ratios: list[float]) -> list[float]:
        if any(not 0 < r < 1 for r in ratios) or ratios != sorted(ratios, reverse=True):
            raise ValueError("LOD ratios are shares of LOD0 between 0 and 1, heaviest first")
        return ratios

    @field_validator("base_color")
    @classmethod
    def _colour(cls, rgba: tuple[float, float, float, float]) -> tuple[float, ...]:
        if any(not 0 <= c <= 1 for c in rgba):
            raise ValueError("colour channels are 0..1")
        return rgba


class LodReport(BaseModel):
    name: str
    triangles: int
    vertices: int
    # how far this LOD's surface strays from LOD0's, sampled (0 for LOD0)
    max_deviation_mm: float


class ColliderReport(BaseModel):
    name: str
    kind: Literal["convex", "box"]
    triangles: int


class GameReport(BaseModel):
    ok: bool
    message: str | None = None
    triangles_in: int = 0
    lods: list[LodReport] = Field(default_factory=list)
    collider: ColliderReport | None = None
    uv: bool = False
    size_m: tuple[float, float, float] | None = None  # x, y (up), z — as the engine sees it
    pivot: str = "base"
    # the paint, as a texture: its size on LOD0 (None = the model had no colours to keep)
    baked_texture_px: int | None = None
    file_bytes: int = 0


def _decimated(mesh: trimesh.Trimesh, faces: int) -> trimesh.Trimesh:
    if len(mesh.faces) <= faces:
        return mesh.copy()
    return mesh.simplify_quadric_decimation(face_count=max(int(faces), 4))


def _lighter(lod0: trimesh.Trimesh, previous: trimesh.Trimesh, faces: int) -> trimesh.Trimesh:
    """The next LOD — unless simplifying would wreck the shape: a model that is already a
    handful of triangles (a box is 12) keeps the previous LOD rather than collapsing into
    a sheet, and so does any result that loses a tenth of its size along some axis."""
    if faces < MIN_LOD_TRIANGLES:
        return previous.copy()
    lighter = _decimated(lod0, faces)
    if (lighter.extents < 0.9 * lod0.extents).any():
        return previous.copy()
    return lighter


def _deviation_mm(lod: trimesh.Trimesh, reference: trimesh.Trimesh) -> float:
    points, _ = trimesh.sample.sample_surface(lod, DEVIATION_SAMPLES, seed=0)
    _, distance, _ = reference.nearest.on_surface(points)
    return round(float(np.max(distance)) * 1000.0, 3)


def face_colours(mesh: trimesh.Trimesh) -> np.ndarray | None:
    """RGBA per face when the mesh carries colours (a painted preview does), else None."""
    visual = mesh.visual
    if not isinstance(visual, trimesh.visual.ColorVisuals) or visual.kind is None:
        return None
    colours: np.ndarray = np.asarray(visual.face_colors, dtype=np.uint8)
    return colours if len(colours) == len(mesh.faces) else None


def _transferred(lod: trimesh.Trimesh, source: trimesh.Trimesh, colours: np.ndarray) -> np.ndarray:
    """Each LOD face takes the colour of the source face nearest its centre."""
    if len(lod.faces) == len(source.faces) and np.array_equal(lod.faces, source.faces):
        return colours
    _, _, nearest = source.nearest.on_surface(lod.triangles_center)
    picked: np.ndarray = colours[np.asarray(nearest, dtype=np.int64)]
    return picked


def _bake(uv: np.ndarray, faces: np.ndarray, colours: np.ndarray, size: int) -> Image.Image:
    """Every face's colour painted over its own UV triangle, then grown into the empty
    texels around each island so texture filtering never samples the background at a seam."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    corners = np.c_[uv[:, 0] * (size - 1), (1.0 - uv[:, 1]) * (size - 1)]  # v runs up
    for face, colour in zip(faces.tolist(), colours.tolist(), strict=True):
        fill = tuple(int(c) for c in colour[:4])
        draw.polygon([tuple(corners[i]) for i in face], fill=fill, outline=fill)
    texels = np.asarray(image).copy()
    filled = texels[..., 3] > 0
    for _ in range(4):
        grown = filled.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            source = np.roll(filled, (dy, dx), axis=(0, 1))
            take = source & ~grown
            texels[take] = np.roll(texels, (dy, dx), axis=(0, 1))[take]
            grown |= take
        filled = grown
    texels[..., 3] = 255
    return Image.fromarray(texels, "RGBA")


def _convex_collider(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    hull: trimesh.Trimesh = mesh.convex_hull
    target = MAX_COLLIDER_TRIANGLES
    while len(hull.faces) > MAX_COLLIDER_TRIANGLES and target >= 8:
        hull = _decimated(hull, target).convex_hull  # re-hulled: decimation may dent it
        target = int(target * 0.8)
    return hull


def build(
    mesh_mm: trimesh.Trimesh, request: GameRequest, colours: np.ndarray | None = None
) -> tuple[trimesh.Scene, GameReport]:
    """A Z-up millimetre mesh in, a Y-up metre scene with LODs and a collider out.

    `colours` (RGBA per face of `mesh_mm`) are baked into a texture per LOD when given.
    """
    mesh = mesh_mm.copy()
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    lo, hi = mesh.bounds
    centre = (lo + hi) / 2.0
    if request.pivot == "base":
        mesh.apply_translation((-centre[0], -centre[1], -lo[2]))
    elif request.pivot == "centre":
        mesh.apply_translation(-centre)
    mesh.apply_scale(0.001)
    mesh.apply_transform(Z_UP_TO_Y_UP)

    lod0 = _decimated(mesh, request.max_triangles)
    lods = [lod0]
    for ratio in request.lod_ratios:
        lods.append(_lighter(lod0, lods[-1], int(len(lod0.faces) * ratio)))
    material = PBRMaterial(
        name=f"{request.name}_Material",
        baseColorFactor=[int(round(c * 255)) for c in request.base_color],
        metallicFactor=request.metallic,
        roughnessFactor=request.roughness,
    )
    bake = colours is not None and request.uv
    scene = trimesh.Scene()
    lod_reports: list[LodReport] = []
    for index, lod in enumerate(lods):
        name = f"{request.name}_LOD{index}"
        deviation = 0.0 if index == 0 else _deviation_mm(lod, lod0)
        shaded = lod.unwrap() if request.uv else lod.copy()
        visual = shaded.visual
        uv = visual.uv if isinstance(visual, trimesh.visual.TextureVisuals) else None
        lod_material = material
        if bake and uv is not None and colours is not None:
            # merge/fix_normals keep face order, so `colours` still match `mesh` face by face
            size = max(request.texture_px >> index, 256)
            texture = _bake(uv, shaded.faces, _transferred(lod, mesh, colours), size)
            lod_material = PBRMaterial(
                name=f"{request.name}_LOD{index}_Material",
                baseColorTexture=texture,
                metallicFactor=request.metallic,
                roughnessFactor=request.roughness,
            )
        shaded.visual = trimesh.visual.TextureVisuals(uv=uv, material=lod_material)
        scene.add_geometry(shaded, node_name=name, geom_name=name)
        lod_reports.append(
            LodReport(
                name=name,
                triangles=len(lod.faces),
                vertices=len(shaded.vertices),
                max_deviation_mm=deviation,
            )
        )

    collider_report: ColliderReport | None = None
    if request.collider != "none":
        shape = (
            _convex_collider(lod0)
            if request.collider == "convex"
            else lod0.bounding_box_oriented.to_mesh()
        )
        name = f"UCX_{request.name}_00"
        scene.add_geometry(shape, node_name=name, geom_name=name)
        collider_report = ColliderReport(
            name=name, kind=request.collider, triangles=len(shape.faces)
        )

    extents = lod0.extents
    return scene, GameReport(
        ok=True,
        triangles_in=len(mesh_mm.faces),
        lods=lod_reports,
        collider=collider_report,
        uv=request.uv,
        size_m=(
            round(float(extents[0]), 6),
            round(float(extents[1]), 6),
            round(float(extents[2]), 6),
        ),
        pivot=request.pivot,
        baked_texture_px=request.texture_px if bake else None,
    )


def export_file(source: Path, source_format: str, request: GameRequest, output: Path) -> GameReport:
    meta = parse(source_format, source)
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        return GameReport(ok=False, message="the file has no mesh to export")
    colours = face_colours(mesh)  # before anything can merge or reorder faces
    mesh = to_platform_axes(mesh.copy(), source_format)
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)
    scene, report = build(mesh, request, colours)
    payload = scene.export(file_type="glb")
    data = payload if isinstance(payload, bytes) else bytes(payload)
    output.write_bytes(data)
    report.file_bytes = len(data)
    return report


def run_in_sandbox(
    source: Path,
    source_format: str,
    request: GameRequest,
    output: Path,
    limits: Any | None = None,
) -> GameReport:
    from worker import sandbox

    outcome = sandbox.run(
        "worker.gameready",
        [source_format, str(source), str(output), request.model_dump_json()],
        input_path=source,
        limits=limits or GAME_LIMITS,
    )
    if not outcome.ok:
        return GameReport(ok=False, message=outcome.message)
    return GameReport.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: gameready <src_fmt> <src> <dst> <request-json>
    source_format, source_path, output_path, payload = sys.argv[1:5]
    try:
        result = export_file(
            Path(source_path),
            source_format,
            GameRequest.model_validate_json(payload),
            Path(output_path),
        )
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
