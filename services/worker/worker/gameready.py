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
import re
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, field_validator, model_validator
from trimesh.visual.material import PBRMaterial

from worker.decimate import decimated as _decimated
from worker.exporters import SceneAnimationInput, animated_glb
from worker.importers.child import parse
from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh, to_platform_axes
from worker.sandbox import SandboxLimits

# Unity refuses convex MeshColliders over 255 triangles; Unreal's UCX hulls are happier small.
MAX_COLLIDER_TRIANGLES = 255
DEVIATION_SAMPLES = 2000
MIN_LOD_TRIANGLES = 64  # below this, fewer triangles only means a wrong shape
GAME_LIMITS = SandboxLimits(wall_seconds=300, cpu_seconds=300, max_output_bytes=128 * 1024**2)
MAX_GAME_SCENE_OBJECTS = 256


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
    triangle_limit: int
    is_convex: bool
    is_watertight: bool
    volume_ratio_pct: float | None
    # Signed distance from the collider's lowest point to the engine ground plane.
    # Negative means the collider crosses below the plane; this is a measured fact,
    # not a claim that a physics simulation has been run.
    floor_offset_mm: float


class UvAtlasReport(BaseModel):
    lod: str
    # Sum of every UV triangle's area within the unit-square atlas. This is an exact
    # geometry metric, not a raster estimate and not a claim that islands never overlap.
    triangle_area_pct: float
    degenerate_triangles: int
    out_of_bounds_vertices: int


class GameReport(BaseModel):
    ok: bool
    message: str | None = None
    triangles_in: int = 0
    lods: list[LodReport] = Field(default_factory=list)
    collider: ColliderReport | None = None
    uv: bool = False
    uv_atlases: list[UvAtlasReport] = Field(default_factory=list)
    size_m: tuple[float, float, float] | None = None  # x, y (up), z — as the engine sees it
    pivot: str = "base"
    # the paint, as a texture: its size on LOD0 (None = the model had no colours to keep)
    baked_texture_px: int | None = None
    file_bytes: int = 0


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


def _uv_atlas_report(name: str, uv: np.ndarray, faces: np.ndarray) -> UvAtlasReport:
    triangles = uv[faces]
    vectors_a = triangles[:, 1] - triangles[:, 0]
    vectors_b = triangles[:, 2] - triangles[:, 0]
    double_areas = np.abs(vectors_a[:, 0] * vectors_b[:, 1] - vectors_a[:, 1] * vectors_b[:, 0])
    return UvAtlasReport(
        lod=name,
        triangle_area_pct=round(float(double_areas.sum()) * 50.0, 2),
        degenerate_triangles=int(np.count_nonzero(double_areas <= 1e-12)),
        out_of_bounds_vertices=int(
            np.count_nonzero(np.any((uv < -1e-6) | (uv > 1.0 + 1e-6), axis=1))
        ),
    )


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


def transfer_face_colours(target: trimesh.Trimesh, source: trimesh.Trimesh) -> np.ndarray | None:
    """Carry source photo/paint colours to a repaired or decimated version of its surface."""
    colours = face_colours(source)
    return None if colours is None else _transferred(target, source, colours)


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


def bake_mesh_texture(
    mesh: trimesh.Trimesh, size: int
) -> tuple[Image.Image | None, dict[str, Any]]:
    """Bake a mesh's own per-face colours into a square texture, honestly reporting when it can't.

    Scan reconstructions are typically STL round-tripped (T-083's repair step included), which
    carries no colour at all — that is the common case this reports as `no_color_data` rather
    than pretending a texture exists.
    """
    colours = face_colours(mesh)
    if colours is None:
        return None, {"texture_baked": False, "reason": "no_color_data"}
    shaded = mesh.unwrap()
    visual = shaded.visual
    uv = visual.uv if isinstance(visual, trimesh.visual.TextureVisuals) else None
    if uv is None or len(shaded.faces) != len(colours):
        return None, {"texture_baked": False, "reason": "unwrap_failed"}
    texture = _bake(uv, shaded.faces, colours, size)
    return texture, {"texture_baked": True, "texture_size": size}


def export_textured_scan_glb(mesh_mm: trimesh.Trimesh, size: int, output: Path) -> dict[str, Any]:
    """Write a canonical-mm, Z-up coloured scan as one textured glTF binary asset."""
    colours = face_colours(mesh_mm)
    if colours is None:
        return {"texture_baked": False, "reason": "no_color_data"}
    shaded = mesh_mm.unwrap()
    visual = shaded.visual
    uv = visual.uv if isinstance(visual, trimesh.visual.TextureVisuals) else None
    if uv is None or len(shaded.faces) != len(colours):
        return {"texture_baked": False, "reason": "unwrap_failed"}
    texture = _bake(uv, shaded.faces, colours, size)
    shaded.apply_scale(0.001)
    shaded.apply_transform(Z_UP_TO_Y_UP)
    material = PBRMaterial(
        name="ScanPhotoMaterial",
        baseColorTexture=texture,
        metallicFactor=0.0,
        roughnessFactor=0.8,
    )
    shaded.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    payload = trimesh.Scene(shaded).export(file_type="glb")
    data = payload if isinstance(payload, bytes) else bytes(payload)
    output.write_bytes(data)
    return {"texture_baked": True, "texture_size": size, "file_bytes": len(data)}


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
    uv_reports: list[UvAtlasReport] = []
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
        if uv is not None:
            uv_reports.append(_uv_atlas_report(name, uv, shaded.faces))
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
            name=name,
            kind=request.collider,
            triangles=len(shape.faces),
            triangle_limit=MAX_COLLIDER_TRIANGLES,
            is_convex=bool(shape.is_convex),
            is_watertight=bool(shape.is_watertight),
            volume_ratio_pct=(
                round(float(shape.volume / lod0.volume) * 100.0, 2)
                if lod0.is_watertight and lod0.volume > 0 and shape.volume > 0
                else None
            ),
            floor_offset_mm=round(float(shape.bounds[0][1]) * 1000.0, 3),
        )

    extents = lod0.extents
    return scene, GameReport(
        ok=True,
        triangles_in=len(mesh_mm.faces),
        lods=lod_reports,
        collider=collider_report,
        uv=request.uv,
        uv_atlases=uv_reports,
        size_m=(
            round(float(extents[0]), 6),
            round(float(extents[1]), 6),
            round(float(extents[2]), 6),
        ),
        pivot=request.pivot,
        baked_texture_px=request.texture_px if bake else None,
    )


_SCENE_NAME_SANITIZE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize_object_name(raw: str, fallback_index: int) -> str:
    """Turn an arbitrary scene node name into a valid, unique-enough GLB identifier.

    `GameRequest.name` must start with a letter and stay within the LOD/UCX naming
    convention's character set; an unrelated scene node label (any Unicode, spaces,
    punctuation) cannot be trusted to already fit that shape.
    """
    cleaned = _SCENE_NAME_SANITIZE.sub("_", raw).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"Obj{fallback_index}_{cleaned}" if cleaned else f"Obj{fallback_index}"
    return cleaned[:40]


class ObjectGameReport(BaseModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    source_name: str = Field(min_length=1, max_length=120)
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    report: GameReport


class SceneGameReport(BaseModel):
    ok: bool
    message: str | None = None
    objects: int = Field(default=0, ge=0, le=MAX_GAME_SCENE_OBJECTS)
    triangles_in: int = Field(default=0, ge=0)
    per_object: list[ObjectGameReport] = Field(default_factory=list)
    pivot: Literal["base", "centre", "keep"] = "base"
    file_bytes: int = Field(default=0, ge=0)
    animations: int = Field(default=0, ge=0, le=1)
    animated_node_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    animation_kind: Literal["revolute", "prismatic"] | None = None

    @model_validator(mode="after")
    def _aggregate_matches_objects(self) -> SceneGameReport:
        if not self.ok:
            return self
        if self.objects < 1:
            raise ValueError("a successful scene report must contain at least one object")
        if len(self.per_object) != self.objects:
            raise ValueError("objects must equal the number of per_object entries")
        if any(not entry.report.ok for entry in self.per_object):
            raise ValueError("every per_object report must be successful")
        if sum(entry.report.triangles_in for entry in self.per_object) != self.triangles_in:
            raise ValueError("triangles_in must equal the sum of per-object triangles_in")
        node_ids = [entry.node_id for entry in self.per_object]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("every per_object node_id must be unique")
        if self.animations == 0:
            if self.animated_node_id is not None or self.animation_kind is not None:
                raise ValueError("an unanimated report cannot name an animation target")
        elif self.animated_node_id not in node_ids or self.animation_kind is None:
            raise ValueError("an animation must target exactly one reported scene object")
        return self


def build_scene(
    objects: list[tuple[str, str, trimesh.Trimesh, np.ndarray | None, np.ndarray]],
    request: GameRequest,
) -> tuple[trimesh.Scene, SceneGameReport]:
    """Build one combined game-ready GLB where every scene object keeps its own LOD/UV/collider.

    `objects` are `(node_id, name, mesh_mm, colours, world_origin_mm)` in platform millimetres,
    Z-up. The linear portion of the stored world transform is already applied to `mesh_mm`,
    while translation stays on a parent scene node. That keeps the exact authored placement
    and gives every object's LODs and UCX collider one shared pivot for a rigid animation.
    This function computes one shared assembly pivot, then delegates every object's local
    geometry to the unchanged single-object `build()` with `pivot="keep"`.
    """
    if not objects:
        return trimesh.Scene(), SceneGameReport(
            ok=False, message="the scene has no visible geometry to export"
        )
    combined_lo = np.array([np.inf, np.inf, np.inf])
    combined_hi = np.array([-np.inf, -np.inf, -np.inf])
    for _, _, mesh_mm, _, origin_mm in objects:
        lo, hi = mesh_mm.bounds
        combined_lo = np.minimum(combined_lo, lo + origin_mm)
        combined_hi = np.maximum(combined_hi, hi + origin_mm)
    centre = (combined_lo + combined_hi) / 2.0
    shared_shift = np.zeros(3, dtype=np.float64)
    if request.pivot == "base":
        shared_shift = np.asarray((-centre[0], -centre[1], -combined_lo[2]))
    elif request.pivot == "centre":
        shared_shift = -centre

    scene = trimesh.Scene()
    per_object: list[ObjectGameReport] = []
    used_names: set[str] = set()
    triangles_in_total = 0
    for index, (node_id, name, mesh_mm, colours, origin_mm) in enumerate(objects):
        base_name = _sanitize_object_name(name, index)
        object_name = base_name
        suffix = index
        while object_name in used_names:
            marker = f"_{suffix}"
            object_name = f"{base_name[: 40 - len(marker)]}{marker}"
            suffix += 1
        used_names.add(object_name)

        object_request = request.model_copy(update={"name": object_name, "pivot": "keep"})
        sub_scene, object_report = build(mesh_mm, object_request, colours)
        platform_origin_m = (origin_mm + shared_shift) * 0.001
        engine_origin = trimesh.transform_points([platform_origin_m], Z_UP_TO_Y_UP)[0]
        parent_transform = np.eye(4)
        parent_transform[:3, 3] = engine_origin
        scene.graph.update(frame_to=object_name, matrix=parent_transform)
        for geom_name, geometry in sub_scene.geometry.items():
            scene.add_geometry(
                geometry,
                node_name=geom_name,
                geom_name=geom_name,
                parent_node_name=object_name,
            )
        per_object.append(
            ObjectGameReport(
                node_id=node_id,
                source_name=name,
                name=object_name,
                report=object_report,
            )
        )
        triangles_in_total += object_report.triangles_in

    return scene, SceneGameReport(
        ok=True,
        objects=len(per_object),
        triangles_in=triangles_in_total,
        per_object=per_object,
        pivot=request.pivot,
    )


def _load_platform_mesh_mm(
    source: Path, source_format: str
) -> tuple[trimesh.Trimesh | None, np.ndarray | None]:
    """Parse a source file into a platform-axes, millimetre mesh and its per-face colours."""
    meta = parse(source_format, source)
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        return None, None
    colours = face_colours(mesh)  # before anything can merge or reorder faces
    mesh = to_platform_axes(mesh.copy(), source_format)
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)
    return mesh, colours


def export_file(source: Path, source_format: str, request: GameRequest, output: Path) -> GameReport:
    mesh, colours = _load_platform_mesh_mm(source, source_format)
    if mesh is None:
        return GameReport(ok=False, message="the file has no mesh to export")
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


class SceneObjectSource(BaseModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    path: str
    format: Literal["stl", "glb"]
    world_transform: list[list[float]]


class GameSceneManifest(BaseModel):
    objects: list[SceneObjectSource] = Field(min_length=1, max_length=MAX_GAME_SCENE_OBJECTS)
    request: GameRequest
    animation: SceneAnimationInput | None = None


def export_scene_file(
    objects: list[SceneObjectSource],
    request: GameRequest,
    output: Path,
    animation: SceneAnimationInput | None = None,
) -> SceneGameReport:
    """Load every visible scene object, apply its exact stored world transform, then build."""
    prepared: list[tuple[str, str, trimesh.Trimesh, np.ndarray | None, np.ndarray]] = []
    for entry in objects:
        mesh, colours = _load_platform_mesh_mm(Path(entry.path), entry.format)
        if mesh is None:
            return SceneGameReport(ok=False, message=f"object {entry.name!r} has no mesh to export")
        transform = np.asarray(entry.world_transform, dtype=np.float64)
        if (
            transform.shape != (4, 4)
            or not np.isfinite(transform).all()
            or not np.allclose(transform[3], (0.0, 0.0, 0.0, 1.0), atol=1e-9)
            or abs(float(np.linalg.det(transform[:3, :3]))) < 1e-12
        ):
            return SceneGameReport(ok=False, message=f"invalid world transform for {entry.name!r}")
        if animation is not None and entry.node_id == animation.node_id:
            if not np.allclose(transform[:3, :3], np.eye(3), rtol=1e-9, atol=1e-9):
                return SceneGameReport(
                    ok=False,
                    message=("game-ready rigid animation needs an axis-aligned mechanism node"),
                )
        linear = transform.copy()
        origin_mm = linear[:3, 3].copy()
        linear[:3, 3] = 0.0
        mesh.apply_transform(linear)
        prepared.append((entry.node_id, entry.name, mesh, colours, origin_mm))
    scene, report = build_scene(prepared, request)
    if not report.ok:
        return report
    payload = scene.export(file_type="glb")
    data = payload if isinstance(payload, bytes) else bytes(payload)
    if animation is not None:
        target = next(
            (entry for entry in report.per_object if entry.node_id == animation.node_id), None
        )
        if target is None:
            return SceneGameReport(ok=False, message="animated scene node is not visible")
        data = animated_glb(data, target.name, animation)
        report.animations = 1
        report.animated_node_id = animation.node_id
        report.animation_kind = animation.kind
    output.write_bytes(data)
    report.file_bytes = len(data)
    return report


def run_scene_in_sandbox(
    objects: list[SceneObjectSource],
    request: GameRequest,
    output: Path,
    limits: Any | None = None,
    *,
    animation: SceneAnimationInput | None = None,
) -> SceneGameReport:
    from worker import sandbox

    effective_limits = limits or GAME_LIMITS
    try:
        combined_input_bytes = sum(Path(entry.path).stat().st_size for entry in objects)
    except OSError as exc:
        return SceneGameReport(ok=False, message=str(exc))
    if combined_input_bytes > effective_limits.max_input_bytes:
        return SceneGameReport(
            ok=False,
            message=(
                f"scene input is {combined_input_bytes} bytes, "
                f"limit {effective_limits.max_input_bytes}"
            ),
        )
    manifest_path = output.parent / "game_scene.json"
    manifest_path.write_text(
        GameSceneManifest(objects=objects, request=request, animation=animation).model_dump_json(),
        encoding="utf-8",
    )
    outcome = sandbox.run(
        "worker.gameready",
        ["scene", str(manifest_path), str(output)],
        input_path=manifest_path,
        limits=effective_limits,
        cwd=output.parent,
    )
    if not outcome.ok:
        return SceneGameReport(ok=False, message=outcome.message)
    return SceneGameReport.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child: gameready <src_fmt> <src> <dst> <request-json>
    #                   or:  gameready scene <manifest.json> <dst>
    try:
        if sys.argv[1] == "scene":
            manifest = GameSceneManifest.model_validate_json(Path(sys.argv[2]).read_text())
            scene_result = export_scene_file(
                manifest.objects,
                manifest.request,
                Path(sys.argv[3]),
                manifest.animation,
            )
            print(json.dumps(scene_result.model_dump(mode="json")))
        else:
            source_format, source_path, output_path, payload = sys.argv[1:5]
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
