"""Orchestrator-facing API: run an importer inside the sandbox and return typed results."""

from __future__ import annotations

from pathlib import Path

from worker import sandbox
from worker.report import ImportFailure, ImportResult

MESH_FORMATS = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf", "dae", "usdz"})
CAD_FORMATS = frozenset({"step", "stp", "iges", "igs"})
SUPPORTED = MESH_FORMATS | CAD_FORMATS
CHILD_MODULE = "worker.importers.child"


def import_metadata(
    path: Path, format_id: str, limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS
) -> ImportResult:
    if format_id in CAD_FORMATS:
        # B-Rep formats are read by the OCCT kernel, which sandboxes itself (T-022).
        from worker.importers.cad import import_cad

        return import_cad(path, format_id)
    if format_id not in MESH_FORMATS:
        return ImportResult(
            ok=False, error=ImportFailure(code="unsupported_format", message=format_id)
        )
    outcome = sandbox.run(CHILD_MODULE, [format_id, str(path)], input_path=path, limits=limits)
    if not outcome.ok:
        assert outcome.failure is not None
        return ImportResult(
            ok=False,
            error=ImportFailure(code=f"sandbox_{outcome.failure.value}", message=outcome.message),
        )
    return ImportResult.model_validate(outcome.output)
