"""Mesh diagnostics (T-027) and repair strategies (T-028..T-030).

Pipeline per docs/04: import -> diagnostics -> repair -> post-repair
diagnostics -> delta report. The source is never modified in place; the
caller receives a new file plus a report that says exactly what changed.
Runs inside the T-017 sandbox via `python -m worker.repair`.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field
from trimesh import repair as trepair

from worker import sandbox
from worker.importers.child import parse
from worker.importers.common import as_single_mesh

DEGENERATE_HEIGHT_MM = 1e-6
MAX_HOLE_LOOP_VERTICES = 512

RepairStep = Literal["normals", "holes", "degenerate"]
ALL_STEPS: tuple[RepairStep, ...] = ("degenerate", "normals", "holes")


class Diagnostics(BaseModel):
    vertices: int
    faces: int
    bodies: int
    watertight: bool
    winding_consistent: bool
    inverted: bool
    boundary_edges: int
    holes: int
    non_manifold_edges: int
    degenerate_faces: int
    duplicate_faces: int
    unreferenced_vertices: int
    euler_number: int
    volume_mm3: float | None
    nan_vertices: int

    @property
    def defects(self) -> list[str]:
        out: list[str] = []
        if self.nan_vertices:
            out.append("nan_vertices")
        if self.degenerate_faces:
            out.append("degenerate_faces")
        if self.duplicate_faces:
            out.append("duplicate_faces")
        if self.non_manifold_edges:
            out.append("non_manifold_edges")
        if self.holes:
            out.append("holes")
        if not self.winding_consistent:
            out.append("inconsistent_winding")
        if self.inverted:
            out.append("inverted_normals")
        if self.unreferenced_vertices:
            out.append("unreferenced_vertices")
        return out


class TopologyDelta(BaseModel):
    faces_removed: int = 0
    faces_added: int = 0
    faces_flipped: int = 0
    vertices_removed: int = 0
    vertices_added: int = 0
    holes_closed: int = 0
    holes_remaining: int = 0


class RepairReport(BaseModel):
    schema_version: Literal[1] = 1
    steps: list[RepairStep]
    before: Diagnostics
    after: Diagnostics
    delta: TopologyDelta
    changed: bool
    printable_after: bool
    notes: list[str] = Field(default_factory=list)


class RepairFailure(BaseModel):
    code: str
    message: str


class RepairOutcome(BaseModel):
    ok: bool
    report: RepairReport | None = None
    output_path: str | None = None
    error: RepairFailure | None = None


# --- diagnostics (T-027) -------------------------------------------------------------------


def diagnose(mesh: trimesh.Trimesh) -> Diagnostics:
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    nan_vertices = int(np.count_nonzero(~np.all(np.isfinite(vertices), axis=1)))
    if len(faces) == 0:
        return Diagnostics(
            vertices=len(vertices),
            faces=0,
            bodies=0,
            watertight=False,
            winding_consistent=False,
            inverted=False,
            boundary_edges=0,
            holes=0,
            non_manifold_edges=0,
            degenerate_faces=0,
            duplicate_faces=0,
            unreferenced_vertices=len(vertices),
            euler_number=0,
            volume_mm3=None,
            nan_vertices=nan_vertices,
        )

    # Each unique edge and how many faces use it: 1 = boundary, >2 = non-manifold.
    _, counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    boundary_edges = int(np.count_nonzero(counts == 1))
    non_manifold = int(np.count_nonzero(counts > 2))
    holes = _boundary_loop_count(mesh) if boundary_edges else 0

    watertight = bool(mesh.is_watertight)
    winding = bool(mesh.is_winding_consistent)
    inverted = bool(watertight and winding and mesh.volume < 0)
    degenerate = int(np.count_nonzero(~mesh.nondegenerate_faces(height=DEGENERATE_HEIGHT_MM)))
    duplicate = int(len(faces) - np.count_nonzero(mesh.unique_faces()))
    referenced = np.zeros(len(vertices), dtype=bool)
    referenced[faces.ravel()] = True
    return Diagnostics(
        vertices=int(len(vertices)),
        faces=int(len(faces)),
        bodies=int(mesh.body_count),
        watertight=watertight,
        winding_consistent=winding,
        inverted=inverted,
        boundary_edges=boundary_edges,
        holes=holes,
        non_manifold_edges=non_manifold,
        degenerate_faces=degenerate,
        duplicate_faces=duplicate,
        unreferenced_vertices=int(np.count_nonzero(~referenced)),
        euler_number=int(mesh.euler_number),
        volume_mm3=float(abs(mesh.volume)) if watertight and winding else None,
        nan_vertices=nan_vertices,
    )


def _boundary_loop_count(mesh: trimesh.Trimesh) -> int:
    try:
        return int(len(mesh.outline().entities))
    except Exception:  # outline() can choke on pathological boundaries
        return 1


# --- repairs (T-028..T-030) -----------------------------------------------------------------


def clean_degenerate(mesh: trimesh.Trimesh) -> None:
    """T-030: merge coincident vertices; drop zero-area/duplicate faces and unused vertices."""
    mesh.merge_vertices()
    keep = mesh.nondegenerate_faces(height=DEGENERATE_HEIGHT_MM) & mesh.unique_faces()
    if not keep.all():
        mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()


def fix_normals(mesh: trimesh.Trimesh) -> int:
    """T-028: make winding consistent and orient outward. Returns faces flipped."""
    before = np.asarray(mesh.faces).copy()
    trepair.fix_normals(mesh, multibody=True)
    after = np.asarray(mesh.faces)
    if before.shape != after.shape:
        return int(len(after))
    return int(np.count_nonzero(np.any(before != after, axis=1)))


def close_holes(mesh: trimesh.Trimesh) -> tuple[int, int]:
    """T-029: fill boundary loops. Small loops via trimesh, larger ones by a centroid fan.
    Returns (holes_closed, holes_remaining)."""
    before = _boundary_loop_count(mesh) if not mesh.is_watertight else 0
    if before == 0:
        return 0, 0
    trepair.fill_holes(mesh)
    if not mesh.is_watertight:
        _fan_fill(mesh)
    remaining = _boundary_loop_count(mesh) if not mesh.is_watertight else 0
    return max(before - remaining, 0), remaining


def _fan_fill(mesh: trimesh.Trimesh) -> None:
    try:
        outline = mesh.outline()
    except Exception:
        return
    new_vertices: list[np.ndarray] = []
    new_faces: list[np.ndarray] = []
    base = len(mesh.vertices)
    for entity in outline.entities:
        loop = np.asarray(entity.points)
        if loop[0] == loop[-1]:
            loop = loop[:-1]
        if len(loop) < 3 or len(loop) > MAX_HOLE_LOOP_VERTICES:
            continue
        centroid = mesh.vertices[loop].mean(axis=0)
        centre = base + len(new_vertices)
        new_vertices.append(centroid)
        for a, b in zip(loop, np.roll(loop, -1), strict=True):
            new_faces.append(np.array([centre, b, a]))
    if not new_faces:
        return
    mesh.vertices = np.vstack([mesh.vertices, np.array(new_vertices)])
    mesh.faces = np.vstack([mesh.faces, np.array(new_faces)])
    trepair.fix_normals(mesh, multibody=True)


def repair_mesh(mesh: trimesh.Trimesh, steps: tuple[RepairStep, ...] = ALL_STEPS) -> RepairReport:
    before = diagnose(mesh)
    delta = TopologyDelta()
    notes: list[str] = []

    if before.nan_vertices:
        keep = np.all(np.isfinite(np.asarray(mesh.vertices, dtype=float)), axis=1)
        mesh.update_vertices(keep)
        notes.append(f"dropped {before.nan_vertices} vertices with NaN/inf coordinates")

    for step in steps:
        if step == "degenerate":
            faces_before, verts_before = len(mesh.faces), len(mesh.vertices)
            clean_degenerate(mesh)
            delta.faces_removed += max(faces_before - len(mesh.faces), 0)
            delta.vertices_removed += max(verts_before - len(mesh.vertices), 0)
        elif step == "normals":
            delta.faces_flipped += fix_normals(mesh)
        elif step == "holes":
            faces_before, verts_before = len(mesh.faces), len(mesh.vertices)
            closed, remaining = close_holes(mesh)
            delta.holes_closed += closed
            delta.holes_remaining = remaining
            delta.faces_added += max(len(mesh.faces) - faces_before, 0)
            delta.vertices_added += max(len(mesh.vertices) - verts_before, 0)
            if remaining:
                notes.append(f"{remaining} hole(s) could not be closed automatically")

    if "normals" in steps and "holes" in steps:
        # Orientation is only well-defined once the surface is closed: re-run after filling.
        delta.faces_flipped += fix_normals(mesh)

    after = diagnose(mesh)
    if before.nan_vertices:
        delta.vertices_removed += before.nan_vertices
    changed = delta != TopologyDelta(holes_remaining=delta.holes_remaining)
    printable = after.watertight and after.winding_consistent and after.degenerate_faces == 0
    return RepairReport(
        steps=list(steps),
        before=before,
        after=after,
        delta=delta,
        changed=changed,
        printable_after=printable,
        notes=notes,
    )


# --- file level -------------------------------------------------------------------------------


def repair_file(source: Path, source_format: str, output: Path) -> RepairReport:
    """Parse (with unit handling), repair, write a canonical-mm binary STL to `output`."""
    meta = parse(source_format, source)
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        skip_materials=True,
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None or mesh.is_empty:
        raise ValueError("source has no mesh geometry")
    mesh = mesh.copy()
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)
    report = repair_mesh(mesh)
    output.write_bytes(_as_bytes(mesh.export(file_type="stl")))
    return report


def _as_bytes(exported: object) -> bytes:
    if isinstance(exported, str):
        return exported.encode()
    if isinstance(exported, bytes | bytearray):
        return bytes(exported)
    raise TypeError(f"unexpected export payload {type(exported).__name__}")


def repair_in_sandbox(
    source: Path,
    source_format: str,
    output: Path,
    limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS,
) -> RepairOutcome:
    """Orchestrator entry: run the repair child under the sandbox and return typed results."""
    outcome = sandbox.run(
        "worker.repair", [source_format, str(source), str(output)], input_path=source, limits=limits
    )
    if not outcome.ok:
        assert outcome.failure is not None
        return RepairOutcome(
            ok=False,
            error=RepairFailure(code=f"sandbox_{outcome.failure.value}", message=outcome.message),
        )
    result = RepairOutcome.model_validate(outcome.output)
    if not result.ok:
        output.unlink(missing_ok=True)
    return result


if __name__ == "__main__":  # sandbox child: repair <format> <source> <output>
    import json
    import sys

    try:
        result = RepairOutcome(
            ok=True,
            report=repair_file(Path(sys.argv[2]), sys.argv[1], Path(sys.argv[3])),
            output_path=sys.argv[3],
        )
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        result = RepairOutcome(
            ok=False,
            error=RepairFailure(code="repair_failed", message=f"{type(exc).__name__}: {exc}"),
        )
    sys.stdout.write(json.dumps(result.model_dump(mode="json")))
