"""Mesh exports (T-024 STL, T-025 GLB, 3MF for F-076) validated by an integrity report.

Pipeline (two sandbox children): parse source + write target with trimesh ->
re-import the output through the importer -> compare. The output is
only kept when the report does not fail; a failed printable gate never
yields a "green" file.
"""

from __future__ import annotations

import io
from pathlib import Path

import trimesh
from pydantic import BaseModel

from worker import sandbox
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
    {"stl", "glb", "3mf", "obj", "ply", "dae", "usdz", "x3d", "x3dv", "wrl", "fbx"}
)
# Formats that carry per-vertex colour, so painting survives the trip out (F-034).
COLOUR_TARGETS = frozenset({"glb", "gltf", "ply", "3mf"})
GLTF_MM_TO_M = 0.001


class ExportOutcome(BaseModel):
    ok: bool
    output_path: str | None = None
    report: IntegrityReport | None = None
    error: ImportFailure | None = None


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
    meta = parse(source_format, source_path)
    mesh: trimesh.Trimesh | None
    if source_format == "usdz":
        # trimesh has no USDZ reader at all; pxr builds the merged mesh directly.
        mesh = usdz_io.load_mesh(source_path)
    elif source_format == "fbx":
        mesh, _ = fbx_io.load_mesh(source_path)
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
    else:
        raise ValueError(f"unsupported target {target_format!r}")
    return meta


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

    try:
        source_meta = convert(Path(sys.argv[3]), sys.argv[1], sys.argv[2], Path(sys.argv[4]))
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        failure = {"ok": False, "code": "convert_failed", "message": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(failure))
    else:
        sys.stdout.write(json.dumps({"ok": True, "source": source_meta.model_dump(mode="json")}))
