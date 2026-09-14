"""Bridge to the C++ geometry-service (OCCT): execute an OperationPlan in the sandbox.

The kernel is a separate binary so a crash or runaway boolean can never take
the worker down; it gets the same limits as any untrusted parser.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from worker.sandbox import SandboxLimits, _preexec

GEOMETRY_BINARY_ENV = "PHYSICAL_AI_GEOMETRY_BIN"
DEFAULT_BINARY = "geometry-service"
KERNEL_LIMITS = SandboxLimits(wall_seconds=120, isolate_network=False)


class BBoxMM(BaseModel):
    min: tuple[float, float, float]
    max: tuple[float, float, float]
    size: tuple[float, float, float]


class BodyResult(BaseModel):
    name: str
    bbox_mm: BBoxMM
    volume_mm3: float
    surface_area_mm2: float
    solids: int
    faces: int
    edges: int
    vertices: int
    valid: bool
    brep: str
    stl: str
    brep_sha256: str = ""
    stl_sha256: str = ""


class KernelFailure(BaseModel):
    code: str
    message: str
    operation_id: str = ""
    operation_type: str = ""


class KernelResult(BaseModel):
    ok: bool
    kernel: str = ""
    service_version: str = ""
    units: str = "mm"
    executed: list[str] = Field(default_factory=list)
    bodies: list[BodyResult] = Field(default_factory=list)
    error: KernelFailure | None = None
    output_dir: str | None = None


def binary_path() -> str | None:
    configured = os.environ.get(GEOMETRY_BINARY_ENV)
    if configured:
        return configured if Path(configured).exists() else None
    return shutil.which(DEFAULT_BINARY)


def available() -> bool:
    return binary_path() is not None


def execute_plan(
    plan: dict[str, Any],
    out_dir: Path,
    *,
    limits: SandboxLimits = KERNEL_LIMITS,
    deflection_mm: float = 0.05,
) -> KernelResult:
    """Run the kernel on a plan; outputs land in `out_dir` (<body>.brep, <body>.stl)."""
    binary = binary_path()
    if binary is None:
        return KernelResult(
            ok=False,
            error=KernelFailure(code="kernel_unavailable", message="geometry-service not found"),
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL")}
    env["OMP_NUM_THREADS"] = "1"  # OCCT's TBB pool stays out of the rlimits' way
    try:
        proc = subprocess.run(
            [binary, "exec", str(plan_path), str(out_dir), "--deflection", str(deflection_mm)],
            capture_output=True,
            timeout=limits.wall_seconds,
            stdin=subprocess.DEVNULL,
            env=env,
            preexec_fn=_preexec(limits),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return KernelResult(
            ok=False,
            error=KernelFailure(
                code="kernel_timeout", message=f"exceeded {limits.wall_seconds}s wall clock"
            ),
        )
    if proc.returncode not in (0, 1) or len(proc.stdout) > limits.max_output_bytes:
        tail = proc.stderr[-2000:].decode("utf-8", "replace")
        return KernelResult(
            ok=False,
            error=KernelFailure(code="kernel_crashed", message=f"exit {proc.returncode}: {tail}"),
        )
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        return KernelResult(
            ok=False, error=KernelFailure(code="kernel_bad_output", message=str(exc))
        )
    result = KernelResult.model_validate(payload)
    result.output_dir = str(out_dir)
    for body in result.bodies:
        body.brep_sha256 = _sha256(out_dir / body.brep)
        body.stl_sha256 = _sha256(out_dir / body.stl)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
