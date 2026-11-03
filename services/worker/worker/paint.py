"""Painting a model (T-106/T-107, F-034): colour per face, kept with the geometry.

Colour is not geometry: a painted model is the same shape, so painting never touches the
mesh — it assigns a colour to the faces the user swept over and writes a format that can
carry it (GLB for viewing, PLY and 3MF for handing on). The strokes themselves are kept, so
a paint layer can be replayed onto a later version of the same part.

The region shapes mirror `app/geometry/region.py` deliberately: the worker stays standalone
(it never imports the API), and a test holds the two shapes to the same JSON.
"""

from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import numpy as np
import trimesh
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from trimesh.visual.material import PBRMaterial

from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh, to_platform_axes

Axis = Literal["x", "y", "z"]
AXES: tuple[Axis, ...] = ("x", "y", "z")
DEFAULT_COLOUR = "#c9ced8"
# What can actually carry the paint out of here. PLY keeps a colour per face exactly; glTF
# and OBJ store colour per vertex, so a stroke's edge blends across one triangle. 3MF stores
# each face's colour as a discrete Core base material, matching PLY without interpolation.
COLOUR_FORMATS = frozenset({"glb", "ply", "obj", "3mf"})
EXACT_COLOUR_FORMATS = frozenset({"ply", "3mf"})


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


class MaterialInput(Strict):
    """One server-resolved immutable catalogue material.

    The worker never accepts a client-authored material property: the API expands a catalogue id
    into this snapshot and the worker independently checks content-addressed texture bytes.
    """

    catalog_material_id: Annotated[str, Field(min_length=1, max_length=120)]
    base_color: Annotated[str, Field(pattern=r"^#[0-9A-F]{6}$")]
    roughness: Annotated[float, Field(ge=0.04, le=1.0)]
    metallic: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    texture_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    texture_tile_size_mm: Annotated[float, Field(ge=10, le=5000)] | None = None
    texture_data_b64: Annotated[str, Field(max_length=500_000)] | None = None

    @model_validator(mode="after")
    def _texture_evidence(self) -> MaterialInput:
        values = (self.texture_sha256, self.texture_tile_size_mm, self.texture_data_b64)
        if any(value is None for value in values) != all(value is None for value in values):
            raise ValueError("material texture hash, tile size and bytes must be supplied together")
        if self.texture_data_b64 is not None:
            try:
                payload = base64.b64decode(self.texture_data_b64, validate=True)
            except ValueError as exc:
                raise ValueError("material texture bytes are not valid base64") from exc
            if hashlib.sha256(payload).hexdigest() != self.texture_sha256:
                raise ValueError("material texture bytes do not match their sha256")
        return self


class Stroke(Strict):
    """One swipe of colour. Without a region it paints the whole body."""

    colour: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    material: MaterialInput | None = None
    opacity: Annotated[float, Field(ge=0.05, le=1.0)] = 1.0
    region: Region | None = None

    @model_validator(mode="after")
    def _one_surface(self) -> Stroke:
        if (self.colour is None) == (self.material is None):
            raise ValueError("a stroke needs exactly one colour or catalogue material")
        return self


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
    materials: list[str] = Field(default_factory=list)
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


def _paint_mesh_state(
    mesh: trimesh.Trimesh, request: PaintRequest
) -> tuple[
    PaintResult,
    trimesh.Trimesh,
    np.ndarray,
    dict[str, MaterialInput],
    np.ndarray,
    np.ndarray,
]:
    """Colour the faces each stroke covers. The shape is untouched; only colour is added."""
    before = len(mesh.faces)
    if before == 0:
        return (
            PaintResult(ok=False, message="the model has no faces to paint"),
            mesh,
            np.empty(0, dtype=object),
            {},
            np.empty(0, dtype=np.float64),
            np.empty((0, 3), dtype=np.uint8),
        )
    mesh, subdivided = _refine_for(mesh, request)
    faces = len(mesh.faces)

    colours = np.tile(np.array([*rgb(request.base_colour), 255], dtype=np.uint8), (faces, 1))
    centres = mesh.triangles_center
    painted = np.zeros(faces, dtype=bool)
    material_ids = np.full(faces, "", dtype=object)
    material_opacities = np.ones(faces, dtype=np.float64)
    material_underlays = colours[:, :3].copy()
    materials: dict[str, MaterialInput] = {}
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
        if stroke.material is not None:
            if stroke.opacity < 1.0 and np.any(material_ids[selected] != ""):
                raise ValueError(
                    "semi-transparent catalogue material cannot overlap another material"
                )
            material_id = stroke.material.catalog_material_id
            existing = materials.get(material_id)
            if existing is not None and existing != stroke.material:
                raise ValueError("one catalogue material id resolved to different snapshots")
            materials[material_id] = stroke.material
            material_underlays[selected] = colours[selected, :3]
            material_opacities[selected] = stroke.opacity
            material_ids[selected] = material_id
            source = np.asarray(rgb(stroke.material.base_color), dtype=float)
            current = colours[selected, :3].astype(float)
            colours[selected, :3] = np.rint(
                current * (1.0 - stroke.opacity) + source * stroke.opacity
            ).astype(np.uint8)
        else:
            assert stroke.colour is not None
            if stroke.opacity < 1.0 and np.any(material_ids[selected] != ""):
                raise ValueError("semi-transparent colour cannot overlap a catalogue material")
            source = np.asarray(rgb(stroke.colour), dtype=float)
            current = colours[selected, :3].astype(float)
            colours[selected, :3] = np.rint(
                current * (1.0 - stroke.opacity) + source * stroke.opacity
            ).astype(np.uint8)
            material_ids[selected] = ""
            material_opacities[selected] = 1.0
            material_underlays[selected] = colours[selected, :3]
        painted |= selected

    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, face_colors=colours)
    used = [request.base_colour, *(s.colour for s in request.strokes if s.colour is not None)]
    return (
        PaintResult(
            ok=True,
            faces=faces,
            faces_before=before,
            painted_faces=int(painted.sum()),
            colours=list(dict.fromkeys(used)),
            materials=list(materials),
            unused_strokes=unused,
            subdivided=subdivided,
        ),
        mesh,
        material_ids,
        materials,
        material_opacities,
        material_underlays,
    )


def paint_mesh_into(
    mesh: trimesh.Trimesh, request: PaintRequest
) -> tuple[PaintResult, trimesh.Trimesh]:
    """Colour the faces each stroke covers. The shape is untouched; only colour is added."""
    result, painted, _, _, _, _ = _paint_mesh_state(mesh, request)
    return result, painted


def _material_uv(mesh: trimesh.Trimesh, tile_size_mm: float) -> np.ndarray:
    """Per-face box projection in physical millimetres; vertices must be unmerged."""
    uv = np.zeros((len(mesh.vertices), 2), dtype=np.float64)
    triangles = mesh.vertices[mesh.faces]
    for index, triangle in enumerate(triangles):
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        axis = int(np.argmax(np.abs(normal)))
        plane = (1, 2) if axis == 0 else (0, 2) if axis == 1 else (0, 1)
        uv[mesh.faces[index]] = triangle[:, plane] / tile_size_mm
    return uv


def _dilate_texture(image: Image.Image) -> Image.Image:
    """Grow atlas texels into a small gutter while keeping the exported surface opaque."""

    texels = np.asarray(image.convert("RGBA")).copy()
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


def _bake_material_composite(
    mesh: trimesh.Trimesh,
    underlays: np.ndarray,
    opacities: np.ndarray,
    material: MaterialInput,
    *,
    size: int = 512,
) -> tuple[trimesh.Trimesh, Image.Image, Image.Image]:
    """Bake one opaque base-colour and metallic/roughness atlas for material opacity.

    Material opacity means surface-finish coverage over the preceding RGB paint, not transparent
    geometry. The catalogue texture is sampled in its real millimetre tile size; every output
    texel has alpha 255. The RGB underlay has the conservative non-metallic, fully rough PBR
    baseline used by the existing colour-only preview.
    """

    shaded = mesh.unwrap()
    visual = shaded.visual
    uv = visual.uv if isinstance(visual, trimesh.visual.TextureVisuals) else None
    if uv is None or len(shaded.faces) != len(underlays):
        raise ValueError("catalogue material opacity atlas unwrap failed")

    source_texture: np.ndarray | None = None
    tile_size_mm = material.texture_tile_size_mm or 1.0
    if material.texture_data_b64 is not None:
        payload = base64.b64decode(material.texture_data_b64, validate=True)
        source_texture = np.asarray(Image.open(io.BytesIO(payload)).convert("RGBA"), dtype=np.uint8)

    base_atlas = np.zeros((size, size, 4), dtype=np.uint8)
    pbr_atlas = np.zeros((size, size, 4), dtype=np.uint8)
    corners = np.c_[uv[:, 0] * (size - 1), (1.0 - uv[:, 1]) * (size - 1)]
    base_factor = np.asarray(rgb(material.base_color), dtype=np.float64) / 255.0

    for face_index, face in enumerate(shaded.faces):
        destination = corners[face]
        minimum = np.maximum(np.floor(destination.min(axis=0)).astype(np.int64), 0)
        maximum = np.minimum(np.ceil(destination.max(axis=0)).astype(np.int64), size - 1)
        if np.any(maximum < minimum):
            continue
        xs, ys = np.meshgrid(
            np.arange(minimum[0], maximum[0] + 1),
            np.arange(minimum[1], maximum[1] + 1),
        )
        sample_x = xs.astype(np.float64) + 0.5
        sample_y = ys.astype(np.float64) + 0.5
        first, second, third = destination
        denominator = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (
            first[1] - third[1]
        )
        if abs(float(denominator)) <= 1e-12:
            continue
        weight_first = (
            (second[1] - third[1]) * (sample_x - third[0])
            + (third[0] - second[0]) * (sample_y - third[1])
        ) / denominator
        weight_second = (
            (third[1] - first[1]) * (sample_x - third[0])
            + (first[0] - third[0]) * (sample_y - third[1])
        ) / denominator
        weight_third = 1.0 - weight_first - weight_second
        inside = (weight_first >= -1e-9) & (weight_second >= -1e-9) & (weight_third >= -1e-9)
        if not np.any(inside):
            continue

        if source_texture is None:
            sampled = np.full((int(inside.sum()), 4), 255, dtype=np.uint8)
        else:
            triangle_mm = shaded.vertices[face]
            normal = np.cross(triangle_mm[1] - triangle_mm[0], triangle_mm[2] - triangle_mm[0])
            axis = int(np.argmax(np.abs(normal)))
            plane = (1, 2) if axis == 0 else (0, 2) if axis == 1 else (0, 1)
            projected = triangle_mm[:, plane] / tile_size_mm
            tiled = (
                weight_first[inside, None] * projected[0]
                + weight_second[inside, None] * projected[1]
                + weight_third[inside, None] * projected[2]
            )
            source_x = np.floor(np.mod(tiled[:, 0], 1.0) * source_texture.shape[1]).astype(np.int64)
            source_y = np.floor((1.0 - np.mod(tiled[:, 1], 1.0)) * source_texture.shape[0]).astype(
                np.int64
            )
            source_y %= source_texture.shape[0]
            sampled = source_texture[source_y, source_x]

        coverage = opacities[face_index] * (sampled[:, 3:4].astype(np.float64) / 255.0)
        material_rgb = sampled[:, :3].astype(np.float64) * base_factor
        underlay = underlays[face_index].astype(np.float64)
        composed = np.rint(underlay * (1.0 - coverage) + material_rgb * coverage)
        base_pixels = np.c_[np.clip(composed, 0, 255).astype(np.uint8), np.full(len(sampled), 255)]

        roughness = np.rint((1.0 - coverage[:, 0] + material.roughness * coverage[:, 0]) * 255)
        metallic = np.rint(material.metallic * coverage[:, 0] * 255)
        pbr_pixels = np.c_[
            np.full(len(sampled), 255),
            np.clip(roughness, 0, 255).astype(np.uint8),
            np.clip(metallic, 0, 255).astype(np.uint8),
            np.full(len(sampled), 255),
        ]
        base_atlas[ys[inside], xs[inside]] = base_pixels
        pbr_atlas[ys[inside], xs[inside]] = pbr_pixels

    return (
        shaded,
        _dilate_texture(Image.fromarray(base_atlas, "RGBA")),
        _dilate_texture(Image.fromarray(pbr_atlas, "RGBA")),
    )


def _painted_glb(
    mesh: trimesh.Trimesh,
    colours: np.ndarray,
    material_ids: np.ndarray,
    materials: dict[str, MaterialInput],
    material_opacities: np.ndarray,
    material_underlays: np.ndarray,
) -> bytes:
    """Export exact face groups with real PBR materials and repeatable box-projected maps."""
    scene = trimesh.Scene()
    plain_faces = np.flatnonzero(material_ids == "")
    if plain_faces.size:
        plain = cast(trimesh.Trimesh, mesh.submesh([plain_faces], append=True, repair=False))
        plain.visual = trimesh.visual.ColorVisuals(mesh=plain, face_colors=colours[plain_faces])
        plain.unmerge_vertices()
        plain.apply_scale(0.001)
        plain.apply_transform(Z_UP_TO_Y_UP)
        scene.add_geometry(plain, node_name="PaintColour", geom_name="PaintColour")

    for material_id, material in materials.items():
        face_ids = np.flatnonzero(material_ids == material_id)
        if not face_ids.size:
            continue
        part = cast(trimesh.Trimesh, mesh.submesh([face_ids], append=True, repair=False))
        part.unmerge_vertices()
        if np.any(material_opacities[face_ids] < 1.0):
            part, image, pbr_image = _bake_material_composite(
                part,
                material_underlays[face_ids],
                material_opacities[face_ids],
                material,
            )
            uv = cast(trimesh.visual.TextureVisuals, part.visual).uv
            pbr = PBRMaterial(
                name=material_id,
                baseColorFactor=[255, 255, 255, 255],
                baseColorTexture=image,
                metallicFactor=1.0,
                roughnessFactor=1.0,
                metallicRoughnessTexture=pbr_image,
                alphaMode="OPAQUE",
            )
        else:
            image = None
            uv = None
            if material.texture_data_b64 is not None:
                payload = base64.b64decode(material.texture_data_b64, validate=True)
                image = Image.open(io.BytesIO(payload)).convert("RGBA")
                uv = _material_uv(part, material.texture_tile_size_mm or 1.0)
            pbr = PBRMaterial(
                name=material_id,
                baseColorFactor=[*rgb(material.base_color), 255],
                baseColorTexture=image,
                metallicFactor=material.metallic,
                roughnessFactor=material.roughness,
                alphaMode="OPAQUE",
            )
        part.visual = trimesh.visual.TextureVisuals(uv=uv, material=pbr)
        part.apply_scale(0.001)
        part.apply_transform(Z_UP_TO_Y_UP)
        safe_name = "Material_" + hashlib.sha256(material_id.encode()).hexdigest()[:12]
        scene.add_geometry(part, node_name=safe_name, geom_name=safe_name)
    payload = scene.export(file_type="glb")
    if not isinstance(payload, bytes):
        raise ValueError("GLB exporter did not return bytes")
    return payload


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
    mesh = to_platform_axes(mesh.copy(), source_format)

    result, mesh, material_ids, materials, material_opacities, material_underlays = (
        _paint_mesh_state(mesh, request)
    )
    if not result.ok:
        return result

    payload: bytes | str | dict[str, Any]
    if target_format == "glb":
        if not isinstance(mesh.visual, trimesh.visual.ColorVisuals):
            return PaintResult(ok=False, message="painted mesh has no face colours")
        face_colours = np.asarray(mesh.visual.face_colors, dtype=np.uint8)
        payload = _painted_glb(
            mesh,
            face_colours,
            material_ids,
            materials,
            material_opacities,
            material_underlays,
        )
    elif target_format == "ply":
        payload = mesh.export(file_type="ply", encoding="binary")  # PLY keeps face colours
    elif target_format == "3mf":
        from worker.exporters import _write_3mf

        _write_3mf(mesh, output)
        return result
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
