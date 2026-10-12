"""Mesh exports (T-024 STL, T-025 GLB, 3MF for F-076) validated by an integrity report.

Pipeline (two sandbox children): parse source + write target with trimesh ->
re-import the output through the importer -> compare. The output is
only kept when the report does not fail; a failed printable gate never
yields a "green" file.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from trimesh.visual.material import PBRMaterial
from trimesh.visual.texture import TextureVisuals

from worker import sandbox
from worker.importers import alembic as alembic_io
from worker.importers import fbx as fbx_io
from worker.importers import import_metadata, web3d
from worker.importers import usdz as usdz_io
from worker.importers.child import parse
from worker.importers.common import Z_UP_TO_Y_UP, as_single_mesh, to_platform_axes
from worker.integrity import CheckStatus, IntegrityReport, build_report
from worker.report import ImportFailure, ImportMetadata

# What a user can ask for back (F-014). STEP/IGES come out of the kernel, not trimesh, and
# are import-only here until CAD-ready export lands (F-078).
SUPPORTED_TARGETS = frozenset(
    {
        "stl",
        "glb",
        "3mf",
        "obj",
        "ply",
        "dae",
        "usdz",
        "x3d",
        "x3dv",
        "wrl",
        "fbx",
        "abc",
    }
)
# Formats that carry per-vertex colour, so painting survives the trip out (F-034).
COLOUR_TARGETS = frozenset({"glb", "gltf", "ply", "3mf"})
GLTF_MM_TO_M = 0.001


class ExportOutcome(BaseModel):
    ok: bool
    output_path: str | None = None
    report: IntegrityReport | None = None
    error: ImportFailure | None = None


class SceneMeshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: str
    format: str
    name: str = Field(min_length=1, max_length=120)
    world_transform: list[list[float]]
    appearance: SceneAppearanceInput | None = None
    texture_path: str | None = None


class SceneAppearanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    catalog_material_id: str = Field(min_length=1, max_length=120)
    base_color: str = Field(pattern=r"^#[0-9A-F]{6}$")
    gloss_pct: int = Field(ge=0, le=100)
    roughness: float = Field(ge=0.04, le=1)
    texture_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    texture_tile_size_mm: float | None = Field(default=None, ge=10, le=5000)

    @model_validator(mode="after")
    def texture_pair(self) -> SceneAppearanceInput:
        if (self.texture_sha256 is None) != (self.texture_tile_size_mm is None):
            raise ValueError("texture hash and tile size must be supplied together")
        expected = max(0.04, min(1.0, 1.0 - self.gloss_pct / 100.0))
        if abs(self.roughness - expected) > 1e-9:
            raise ValueError("roughness does not match gloss percentage")
        return self


SceneMeshInput.model_rebuild()


def export_scene(
    inputs: list[SceneMeshInput],
    target_format: str,
    output_path: Path,
    *,
    printable_gate: bool = False,
    limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS,
) -> ExportOutcome:
    """Export visible scene objects after applying the exact stored world matrices."""
    if not inputs:
        return ExportOutcome(
            ok=False,
            error=ImportFailure(code="scene_empty", message="the scene has no visible objects"),
        )
    if target_format not in SUPPORTED_TARGETS:
        return ExportOutcome(
            ok=False, error=ImportFailure(code="unsupported_target", message=target_format)
        )
    manifest = output_path.parent / "scene.json"
    manifest.write_text(
        json.dumps([entry.model_dump(mode="json") for entry in inputs]), encoding="utf-8"
    )
    outcome = sandbox.run(
        "worker.exporters",
        ["scene", target_format, str(manifest), str(output_path)],
        input_path=manifest,
        limits=limits,
        cwd=output_path.parent,
    )
    if not outcome.ok:
        assert outcome.failure is not None
        return ExportOutcome(
            ok=False,
            error=ImportFailure(code=f"sandbox_{outcome.failure.value}", message=outcome.message),
        )
    payload = outcome.output or {}
    if not payload.get("ok"):
        return ExportOutcome(
            ok=False,
            error=ImportFailure(
                code=str(payload.get("code", "convert_failed")),
                message=str(payload.get("message", "")),
            ),
        )
    output_meta = import_metadata(output_path, target_format, limits=limits)
    if not output_meta.ok or output_meta.metadata is None:
        output_path.unlink(missing_ok=True)
        return ExportOutcome(ok=False, error=output_meta.error)
    # The assembled output is its own reference for integrity/printability. Each source was
    # independently parsed before composition; this gate validates what will be downloaded.
    report = build_report(output_meta.metadata, output_meta.metadata, printable_gate=printable_gate)
    if report.status is CheckStatus.failed:
        output_path.unlink(missing_ok=True)
        return ExportOutcome(ok=False, report=report)
    return ExportOutcome(ok=True, output_path=str(output_path), report=report)


def export_mesh(
    source_path: Path,
    source_format: str,
    target_format: str,
    output_path: Path,
    *,
    printable_gate: bool = False,
    limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS,
) -> ExportOutcome:
    """Orchestrator entry: source parsing and conversion run inside the sandbox."""
    if target_format not in SUPPORTED_TARGETS:
        return ExportOutcome(
            ok=False, error=ImportFailure(code="unsupported_target", message=target_format)
        )
    outcome = sandbox.run(
        "worker.exporters",
        [source_format, target_format, str(source_path), str(output_path)],
        input_path=source_path,
        limits=limits,
    )
    if not outcome.ok:
        assert outcome.failure is not None
        return ExportOutcome(
            ok=False,
            error=ImportFailure(code=f"sandbox_{outcome.failure.value}", message=outcome.message),
        )
    payload = outcome.output or {}
    if not payload.get("ok"):
        return ExportOutcome(
            ok=False,
            error=ImportFailure(
                code=str(payload.get("code", "convert_failed")),
                message=str(payload.get("message", "")),
            ),
        )
    source_meta = ImportMetadata.model_validate(payload["source"])

    output_meta = import_metadata(output_path, target_format, limits=limits)
    if not output_meta.ok or output_meta.metadata is None:
        output_path.unlink(missing_ok=True)
        return ExportOutcome(ok=False, error=output_meta.error)

    report = build_report(source_meta, output_meta.metadata, printable_gate=printable_gate)
    if report.status is CheckStatus.failed:
        output_path.unlink(missing_ok=True)
        return ExportOutcome(ok=False, report=report)
    return ExportOutcome(ok=True, output_path=str(output_path), report=report)


# --- in-sandbox conversion -------------------------------------------------------------------


def convert(
    source_path: Path, source_format: str, target_format: str, output_path: Path
) -> ImportMetadata:
    """Parse the source (its metadata is returned for the report) and write the target."""
    mesh, meta = _load_platform_mesh(source_path, source_format)
    _write_mesh(mesh, target_format, output_path)
    return meta


def _load_platform_mesh(
    source_path: Path, source_format: str
) -> tuple[trimesh.Trimesh, ImportMetadata]:
    meta = parse(source_format, source_path)
    mesh: trimesh.Trimesh | None
    if source_format == "usdz":
        # trimesh has no USDZ reader at all; pxr builds the merged mesh directly.
        mesh = usdz_io.load_mesh(source_path)
    elif source_format == "fbx":
        mesh, _ = fbx_io.load_mesh(source_path)
    elif source_format == "abc":
        mesh = alembic_io.load_mesh(source_path)
    elif source_format in ("x3d", "x3dv", "wrl"):
        # nor an X3D/VRML97 one; ours flattens the scene graph Z-up, in the file's units
        mesh, _, _ = web3d.load_mesh(source_path, source_format)
    else:
        loaded = trimesh.load(
            io.BytesIO(source_path.read_bytes()),
            file_type=source_format,
            force="mesh" if source_format in ("stl", "obj", "ply", "dae") else "scene",
            skip_materials=True,
            process=False,
        )
        mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        raise ValueError("source has no mesh geometry")
    mesh = to_platform_axes(mesh.copy(), source_format)
    mesh.merge_vertices()
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)  # canonical mm inside the platform
    return mesh, meta


def _write_mesh(mesh: trimesh.Trimesh, target_format: str, output_path: Path) -> None:
    if target_format == "stl":
        output_path.write_bytes(_as_bytes(mesh.export(file_type="stl")))
    elif target_format == "glb":
        # GLB is glTF in one file; a .gltf export is a JSON plus separate buffers, which
        # does not fit an asset that must be a single downloadable object.
        mesh.apply_scale(GLTF_MM_TO_M)  # glTF is metres and Y-up by spec
        mesh.apply_transform(Z_UP_TO_Y_UP)
        output_path.write_bytes(_as_bytes(trimesh.Scene(mesh).export(file_type="glb")))
    elif target_format == "3mf":
        scene = trimesh.Scene(mesh)
        scene.units = "millimeter"
        output_path.write_bytes(_as_bytes(scene.export(file_type="3mf")))
    elif target_format == "obj":
        # OBJ has no unit statement; the platform's canonical millimetres are what we write.
        output_path.write_bytes(_as_bytes(mesh.export(file_type="obj", include_color=True)))
    elif target_format == "ply":
        output_path.write_bytes(_as_bytes(mesh.export(file_type="ply", encoding="binary")))
    elif target_format == "dae":
        output_path.write_bytes(_fix_collada_asset(_as_bytes(mesh.export(file_type="dae"))))
    elif target_format == "usdz":
        usdz_io.write_usdz(mesh, output_path)
    elif target_format == "x3d":
        web3d.write_x3d(mesh, output_path)
    elif target_format == "wrl":
        web3d.write_wrl(mesh, output_path)
    elif target_format == "x3dv":
        web3d.write_x3dv(mesh, output_path)
    elif target_format == "fbx":
        fbx_io.write_fbx(mesh, output_path)
    elif target_format == "abc":
        alembic_io.write_alembic(mesh, output_path)
    else:
        raise ValueError(f"unsupported target {target_format!r}")


def convert_scene(manifest_path: Path, target_format: str, output_path: Path) -> dict[str, Any]:
    entries = [
        SceneMeshInput.model_validate(item) for item in json.loads(manifest_path.read_text())
    ]
    meshes: list[trimesh.Trimesh] = []
    glb_scene = trimesh.Scene() if target_format == "glb" else None
    used_glb_names: set[str] = set()
    for entry in entries:
        mesh, _ = _load_platform_mesh(Path(entry.path), entry.format)
        transform = np.asarray(entry.world_transform, dtype=np.float64)
        if transform.shape != (4, 4) or not np.isfinite(transform).all():
            raise ValueError(f"invalid world transform for {entry.name}")
        if entry.appearance is not None:
            _apply_scene_appearance(mesh, entry)
        if glb_scene is not None:
            # glTF coordinates are metres and Y-up. Keep each named geometry separate while
            # converting the exact platform-mm world transform into that coordinate system.
            axis = np.asarray(Z_UP_TO_Y_UP, dtype=np.float64)
            scale = np.eye(4)
            scale[:3, :3] *= GLTF_MM_TO_M
            glb_transform = axis @ scale @ transform
            export_name = entry.name
            if export_name in used_glb_names:
                export_name = f"{entry.name} [{entry.node_id}]"
            used_glb_names.add(export_name)
            glb_scene.add_geometry(
                mesh,
                node_name=export_name,
                geom_name=export_name,
                transform=glb_transform,
            )
        else:
            mesh.apply_transform(transform)
            meshes.append(mesh)
    if glb_scene is not None:
        output_path.write_bytes(_as_bytes(glb_scene.export(file_type="glb")))
        return {"objects": len(entries)}
    merged = cast(trimesh.Trimesh, trimesh.util.concatenate(meshes))
    _write_mesh(merged, target_format, output_path)
    return {"objects": len(meshes)}


def _apply_scene_appearance(mesh: trimesh.Trimesh, entry: SceneMeshInput) -> None:
    appearance = entry.appearance
    assert appearance is not None
    colour = [int(appearance.base_color[index : index + 2], 16) for index in (1, 3, 5)] + [255]
    texture: Image.Image | None = None
    uv: np.ndarray | None = None
    if appearance.texture_sha256 is not None:
        if entry.texture_path is None:
            raise ValueError(f"missing texture for assigned material on {entry.name}")
        texture_data = Path(entry.texture_path).read_bytes()
        if hashlib.sha256(texture_data).hexdigest() != appearance.texture_sha256:
            raise ValueError(f"texture hash mismatch for {entry.name}")
        texture = Image.open(io.BytesIO(texture_data)).convert("RGB")
        if texture.width > 512 or texture.height > 512 or texture.width <= 0 or texture.height <= 0:
            raise ValueError(f"unsupported texture dimensions for {entry.name}")
        mesh.unmerge_vertices()
        uv = _box_project_uv(mesh, appearance.texture_tile_size_mm or 1.0)
    material = PBRMaterial(
        name=appearance.catalog_material_id,
        baseColorFactor=colour,
        baseColorTexture=texture,
        metallicFactor=0.0,
        roughnessFactor=appearance.roughness,
    )
    mesh.visual = TextureVisuals(uv=uv, material=material)


def _box_project_uv(mesh: trimesh.Trimesh, tile_size_mm: float) -> np.ndarray:
    """Deterministic per-triangle dominant-axis projection in object-local millimetres."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    uv = np.zeros((len(vertices), 2), dtype=np.float64)
    for face in faces:
        triangle = vertices[face]
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        axis = int(np.argmax(np.abs(normal)))  # numpy's first maximum gives X, then Y, then Z
        projected = triangle[:, (1, 2) if axis == 0 else (0, 2) if axis == 1 else (0, 1)]
        uv[face] = projected / tile_size_mm
    return uv


def _fix_collada_asset(data: bytes) -> bytes:
    """trimesh's COLLADA writer emits raw (already Z-up, already mm) coordinates but tags
    the file `<up_axis>Y_UP</up_axis>` and no `<unit>` at all — both defaults pycollada's
    Collada() applies regardless of what was actually written. A compliant reader (anything
    other than this same trimesh loader, which ignores both fields) would take that at face
    value and rotate/rescale a correct file into a wrong one. Fix the two tags in place;
    nothing else about the XML changes."""
    data = data.replace(b"<up_axis>Y_UP</up_axis>", b"<up_axis>Z_UP</up_axis>")
    return data.replace(b"</asset>", b'<unit meter="0.001" name="millimeter"/></asset>')


def _as_bytes(exported: object) -> bytes:
    if isinstance(exported, str):
        return exported.encode()
    if isinstance(exported, bytes | bytearray):
        return bytes(exported)
    raise TypeError(f"unexpected export payload {type(exported).__name__}")


if __name__ == "__main__":  # sandbox child: convert <src_fmt> <dst_fmt> <src> <dst>
    import json
    import sys

    scene_report: dict[str, Any] | None
    source_meta: ImportMetadata | None
    try:
        if sys.argv[1] == "scene":
            scene_report = convert_scene(Path(sys.argv[3]), sys.argv[2], Path(sys.argv[4]))
            source_meta = None
        else:
            source_meta = convert(Path(sys.argv[3]), sys.argv[1], sys.argv[2], Path(sys.argv[4]))
            scene_report = None
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        failure = {"ok": False, "code": "convert_failed", "message": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(failure))
    else:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "source": source_meta.model_dump(mode="json") if source_meta else None,
                    "scene": scene_report,
                }
            )
        )
