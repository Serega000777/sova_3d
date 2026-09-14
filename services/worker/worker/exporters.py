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
from worker.importers import import_metadata
from worker.importers.child import parse
from worker.importers.common import as_single_mesh
from worker.integrity import CheckStatus, IntegrityReport, build_report
from worker.report import ImportFailure, ImportMetadata

SUPPORTED_TARGETS = frozenset({"stl", "glb", "3mf"})
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
    loaded = trimesh.load(
        io.BytesIO(source_path.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        skip_materials=True,
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        raise ValueError("source has no mesh geometry")
    mesh = mesh.copy()
    mesh.merge_vertices()
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)  # canonical mm inside the platform

    if target_format == "stl":
        output_path.write_bytes(_as_bytes(mesh.export(file_type="stl")))
    elif target_format == "glb":
        mesh.apply_scale(GLTF_MM_TO_M)  # glTF is metres by spec
        output_path.write_bytes(_as_bytes(trimesh.Scene(mesh).export(file_type="glb")))
    elif target_format == "3mf":
        scene = trimesh.Scene(mesh)
        scene.units = "millimeter"
        output_path.write_bytes(_as_bytes(scene.export(file_type="3mf")))
    else:
        raise ValueError(f"unsupported target {target_format!r}")
    return meta


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
