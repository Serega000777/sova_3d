"""Shared kernel step: run a validated OperationPlan and bring back the bodies.

Both the AI command (T-045) and the manual edit (T-055) end here, so a plan
executes exactly one way no matter who authored it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from worker import geometry as kernel
from worker.geometry import BodyResult

from app.geometry.operations import OperationPlan
from app.jobs.runner import JobFailureError


@dataclass(frozen=True, slots=True)
class ExecutedPlan:
    main: BodyResult
    stl: bytes
    brep: bytes
    bodies: list[dict[str, Any]]
    kernel: str
    # every expected body's files, by name — a plan with several parts (F-036) keeps them all
    parts: dict[str, tuple[bytes, bytes]] = field(default_factory=dict)


def run_plan(plan: OperationPlan) -> ExecutedPlan:
    """Execute in the sandboxed kernel binary; a failure is reported per operation."""
    with tempfile.TemporaryDirectory(prefix="kernel-") as tmp:
        result = kernel.execute_plan(plan.model_dump(mode="json"), Path(tmp) / "out")
        if not result.ok or not result.bodies:
            error = result.error
            raise JobFailureError(
                error.code if error else "kernel_failed",
                user_safe_kernel_message(
                    error.code if error else "", error.message if error else ""
                ),
                details={
                    "operation_id": error.operation_id if error else None,
                    "operation_type": error.operation_type if error else None,
                    "kernel_message": error.message if error else None,
                },
            )
        expected = set(plan.expected_outputs) or {result.bodies[-1].name}
        main = next((b for b in result.bodies if b.name in expected), result.bodies[-1])
        out_dir = Path(result.output_dir or tmp)
        if not main.stl or not main.brep:
            raise JobFailureError("kernel_bad_output", "the kernel named no files for the body")
        parts = {
            b.name: ((out_dir / b.stl).read_bytes(), (out_dir / b.brep).read_bytes())
            for b in result.bodies
            if b.name in expected and b.stl and b.brep
        }
        return ExecutedPlan(
            main=main,
            stl=(out_dir / main.stl).read_bytes(),
            brep=(out_dir / main.brep).read_bytes(),
            bodies=[b.model_dump() for b in result.bodies],
            kernel=result.kernel,
            parts=parts,
        )


def user_safe_kernel_message(code: str, detail: str) -> str:
    """Translate kernel error codes into something a maker can act on (docs/04)."""
    messages = {
        "fillet_failed": "The rounding radius is too large for those edges; try a smaller radius.",
        "chamfer_failed": "The chamfer distance is too large for those edges; try a smaller value.",
        "boolean_failed": "Two shapes could not be combined; check that they overlap as intended.",
        "no_face_selected": "No flat face points in that direction on this body.",
        "no_edges_selected": "No edges matched the selection.",
        "unknown_body": "The plan refers to a body that does not exist.",
        "invalid_topology": "The result was not a valid solid, so it was discarded.",
        "kernel_timeout": "The geometry took too long to compute; simplify the request.",
        "kernel_unavailable": "The geometry engine is not available on this worker.",
    }
    return messages.get(code, f"The geometry engine could not complete this step ({code}).")
