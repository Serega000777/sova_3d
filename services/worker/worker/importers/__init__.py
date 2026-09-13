"""Orchestrator-facing API: run an importer inside the sandbox and return typed results."""

from __future__ import annotations

from pathlib import Path

from worker import sandbox
from worker.report import ImportFailure, ImportResult

SUPPORTED = frozenset({"stl", "obj", "ply", "glb", "gltf", "3mf"})
CHILD_MODULE = "worker.importers.child"


def import_metadata(
    path: Path, format_id: str, limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS
) -> ImportResult:
    if format_id not in SUPPORTED:
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
