"""Mesh diagnostics (T-027) and repair strategies (T-028..T-030).

Pipeline per docs/04: import -> diagnostics -> repair -> post-repair
diagnostics -> delta report. The source is never modified in place; the
caller receives a new file plus a report that says exactly what changed.
Runs inside the T-017 sandbox via `python -m worker.repair`.
"""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Literal, cast

import numpy as np
import trimesh
from pydantic import BaseModel, Field
from trimesh import repair as trepair

from worker import sandbox
from worker.importers.child import parse
from worker.importers.common import as_single_mesh, to_platform_axes

DEGENERATE_HEIGHT_MM = 1e-6
MAX_HOLE_LOOP_VERTICES = 512
MIN_FRAGMENT_SIZE_MM = 0.1
MAX_FRAGMENT_SIZE_MM = 1000.0

RepairStep = Literal["normals", "holes", "degenerate", "fragments"]
DefectKind = Literal[
    "large_hole", "floating_fragment", "surface_break", "noise_fragment", "normal_issue"
]
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
    bodies_removed: int = 0


class DefectInstance(BaseModel):
    id: str
    kind: DefectKind
    center_mm: tuple[float, float, float]
    size_mm: float
    count: int = 1


class RepairReport(BaseModel):
    schema_version: Literal[1] = 1
    steps: list[RepairStep]
    before: Diagnostics
    after: Diagnostics
    delta: TopologyDelta
    changed: bool
    printable_after: bool
    fragment_max_size_mm: float | None = None
    notes: list[str] = Field(default_factory=list)
    detected_defects: list[DefectInstance] = Field(default_factory=list)
    remaining_defects: list[DefectInstance] = Field(default_factory=list)


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


def _defect_id(kind: DefectKind, points: np.ndarray) -> str:
    canonical = np.round(np.asarray(points, dtype=float), decimals=6)
    if canonical.ndim == 1:
        canonical = canonical.reshape(1, -1)
    order = np.lexsort((canonical[:, 2], canonical[:, 1], canonical[:, 0]))
    digest = hashlib.sha256(canonical[order].tobytes()).hexdigest()[:20]
    return f"{kind}:{digest}"


def _instance(kind: DefectKind, points: np.ndarray, *, count: int = 1) -> DefectInstance:
    coords = np.asarray(points, dtype=float)
    center = coords.mean(axis=0)
    extent = float(np.max(np.ptp(coords, axis=0))) if len(coords) > 1 else 0.0
    return DefectInstance(
        id=_defect_id(kind, coords),
        kind=kind,
        center_mm=(float(center[0]), float(center[1]), float(center[2])),
        size_mm=extent,
        count=count,
    )


def detect_defects(mesh: trimesh.Trimesh) -> list[DefectInstance]:
    """Return stable, measured defect instances for selection in web/mobile viewers."""
    defects: list[DefectInstance] = []
    # Formats such as STL repeat the same position for every triangle. Detect topology on a
    # welded copy so an instance keeps the same id before and after a lossless file round trip.
    working = mesh.copy()
    working.merge_vertices()
    working.remove_unreferenced_vertices()
    try:
        outline = working.outline()
        for entity in outline.entities:
            loop = np.asarray(entity.points, dtype=int)
            if len(loop) > 1 and loop[0] == loop[-1]:
                loop = loop[:-1]
            if len(loop) >= 3:
                defects.append(_instance("large_hole", np.asarray(working.vertices)[loop]))
    except Exception:
        pass

    components = cast(list[trimesh.Trimesh], list(working.split(only_watertight=False)))
    if len(components) > 1:
        primary_index = int(np.argmax([float(component.area) for component in components]))
        for index, component in enumerate(components):
            if index != primary_index and len(component.vertices):
                defects.append(_instance("floating_fragment", np.asarray(component.vertices)))

    edges = np.sort(np.asarray(working.edges), axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    for edge in unique_edges[counts > 2]:
        defects.append(_instance("surface_break", np.asarray(working.vertices)[edge]))

    invalid_faces = ~(mesh.nondegenerate_faces(height=DEGENERATE_HEIGHT_MM) & mesh.unique_faces())
    noise_points: list[np.ndarray] = []
    if np.any(invalid_faces):
        noise_points.append(
            np.asarray(mesh.vertices)[np.asarray(mesh.faces)[invalid_faces].ravel()]
        )
    referenced = np.zeros(len(mesh.vertices), dtype=bool)
    if len(mesh.faces):
        referenced[np.asarray(mesh.faces).ravel()] = True
    if np.any(~referenced):
        noise_points.append(np.asarray(mesh.vertices)[~referenced])
    if noise_points:
        points = np.vstack(noise_points)
        defects.append(_instance("noise_fragment", points, count=len(points)))

    diagnostics = diagnose(mesh)
    normal_count = int(not diagnostics.winding_consistent) + int(diagnostics.inverted)
    if normal_count and len(mesh.vertices):
        defects.append(_instance("normal_issue", np.asarray(mesh.vertices), count=normal_count))
    return sorted(defects, key=lambda defect: (defect.kind, defect.id))


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


def close_holes(
    mesh: trimesh.Trimesh, target_defect_ids: frozenset[str] | None = None
) -> tuple[int, int]:
    """T-029: fill boundary loops. Small loops via trimesh, larger ones by a centroid fan.
    Returns (holes_closed, holes_remaining)."""
    before = _boundary_loop_count(mesh) if not mesh.is_watertight else 0
    if before == 0:
        return 0, 0
    if target_defect_ids is None:
        trepair.fill_holes(mesh)
        if not mesh.is_watertight:
            _fan_fill(mesh)
    else:
        _fan_fill(mesh, target_defect_ids)
    remaining = _boundary_loop_count(mesh) if not mesh.is_watertight else 0
    return max(before - remaining, 0), remaining


def _fan_fill(mesh: trimesh.Trimesh, target_defect_ids: frozenset[str] | None = None) -> None:
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
        defect_id = _defect_id("large_hole", np.asarray(mesh.vertices)[loop])
        if target_defect_ids is not None and defect_id not in target_defect_ids:
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


def remove_small_fragments(
    mesh: trimesh.Trimesh,
    max_size_mm: float,
    target_defect_ids: frozenset[str] | None = None,
) -> int:
    """Remove disconnected bodies whose largest bounding-box dimension is at most the limit.

    The largest body by surface area is always retained. This prevents an over-large threshold
    from deleting the whole model and makes this destructive cleanup fail safe.
    """
    if (
        not math.isfinite(max_size_mm)
        or max_size_mm < MIN_FRAGMENT_SIZE_MM
        or max_size_mm > MAX_FRAGMENT_SIZE_MM
    ):
        raise ValueError(
            f"fragment size must be between {MIN_FRAGMENT_SIZE_MM} and {MAX_FRAGMENT_SIZE_MM} mm"
        )
    # STL commonly repeats vertices per triangle; weld a copy before finding bodies. Keep the
    # source byte-for-byte equivalent when no component qualifies for removal.
    working = mesh.copy()
    working.merge_vertices()
    working.remove_unreferenced_vertices()
    components = cast(list[trimesh.Trimesh], list(working.split(only_watertight=False)))
    if len(components) <= 1:
        return 0
    component_areas = [float(component.area) for component in components]
    if not all(math.isfinite(area) and area >= 0 for area in component_areas):
        raise ValueError("fragment surface area is not finite")
    primary = components[int(np.argmax(component_areas))]
    kept: list[trimesh.Trimesh] = []
    removed = 0
    for component in components:
        extent = float(np.max(np.asarray(component.extents, dtype=float)))
        defect_id = _defect_id("floating_fragment", np.asarray(component.vertices))
        selected = target_defect_ids is None or defect_id in target_defect_ids
        if (
            component is not primary
            and selected
            and math.isfinite(extent)
            and extent <= max_size_mm
        ):
            removed += 1
        else:
            kept.append(component)
    if removed:
        combined = cast(trimesh.Trimesh, trimesh.util.concatenate(kept))
        mesh.vertices = np.asarray(combined.vertices)
        mesh.faces = np.asarray(combined.faces)
        mesh.remove_unreferenced_vertices()
    return removed


def repair_mesh(
    mesh: trimesh.Trimesh,
    steps: tuple[RepairStep, ...] = ALL_STEPS,
    *,
    fragment_max_size_mm: float | None = None,
    target_defect_ids: tuple[str, ...] | None = None,
) -> RepairReport:
    if ("fragments" in steps) != (fragment_max_size_mm is not None):
        raise ValueError("fragment cleanup requires exactly one explicit size threshold")
    if target_defect_ids is not None:
        # Match the canonical topology used by detect_defects and keep ids invariant across
        # indexed meshes and STL's repeated per-triangle vertices.
        mesh.merge_vertices()
        mesh.remove_unreferenced_vertices()
    before = diagnose(mesh)
    detected_defects = detect_defects(mesh)
    selected_ids: frozenset[str] | None = None
    if target_defect_ids is not None:
        selected_ids = frozenset(target_defect_ids)
        if not selected_ids or len(selected_ids) != len(target_defect_ids):
            raise ValueError("selected defect ids must be non-empty and unique")
        known = {defect.id for defect in detected_defects}
        if not selected_ids <= known:
            raise ValueError("selected defect id does not belong to the source mesh")
        selected_kinds = {defect.kind for defect in detected_defects if defect.id in selected_ids}
        allowed_kinds: set[DefectKind] = set()
        if "holes" in steps:
            allowed_kinds.add("large_hole")
        if "fragments" in steps:
            allowed_kinds.add("floating_fragment")
        if "degenerate" in steps:
            allowed_kinds.add("noise_fragment")
        if "normals" in steps:
            allowed_kinds.add("normal_issue")
        if not selected_kinds <= allowed_kinds:
            raise ValueError("selected defect kind does not match the requested repair step")
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
            closed, remaining = close_holes(mesh, selected_ids)
            delta.holes_closed += closed
            delta.holes_remaining = remaining
            delta.faces_added += max(len(mesh.faces) - faces_before, 0)
            delta.vertices_added += max(len(mesh.vertices) - verts_before, 0)
            if remaining:
                notes.append(f"{remaining} hole(s) could not be closed automatically")
        elif step == "fragments":
            assert fragment_max_size_mm is not None
            faces_before, verts_before = len(mesh.faces), len(mesh.vertices)
            delta.bodies_removed += remove_small_fragments(mesh, fragment_max_size_mm, selected_ids)
            delta.faces_removed += max(faces_before - len(mesh.faces), 0)
            delta.vertices_removed += max(verts_before - len(mesh.vertices), 0)

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
        fragment_max_size_mm=fragment_max_size_mm,
        notes=notes,
        detected_defects=detected_defects,
        remaining_defects=detect_defects(mesh),
    )


# --- file level -------------------------------------------------------------------------------


def repair_file(
    source: Path,
    source_format: str,
    output: Path,
    *,
    fragment_max_size_mm: float | None = None,
    steps: tuple[RepairStep, ...] | None = None,
    target_defect_ids: tuple[str, ...] | None = None,
) -> RepairReport:
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
    mesh = to_platform_axes(mesh.copy(), source_format)
    if meta.scale_to_mm != 1.0:
        mesh.apply_scale(meta.scale_to_mm)
    report = repair_mesh(
        mesh,
        steps=("fragments",) if fragment_max_size_mm is not None else (steps or ALL_STEPS),
        fragment_max_size_mm=fragment_max_size_mm,
        target_defect_ids=target_defect_ids,
    )
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
    *,
    fragment_max_size_mm: float | None = None,
    steps: tuple[RepairStep, ...] | None = None,
    target_defect_ids: tuple[str, ...] | None = None,
) -> RepairOutcome:
    """Orchestrator entry: run the repair child under the sandbox and return typed results."""
    args = [source_format, str(source), str(output)]
    if fragment_max_size_mm is not None:
        args.append(str(fragment_max_size_mm))
    elif steps is not None:
        if not steps or any(step == "fragments" for step in steps):
            raise ValueError("selective repair requires non-fragment steps")
        args.append("steps=" + ",".join(steps))
    if target_defect_ids is not None:
        args.append("ids=" + ",".join(target_defect_ids))
    outcome = sandbox.run("worker.repair", args, input_path=source, limits=limits)
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


if __name__ == "__main__":  # sandbox child: repair <format> <source> <output> [fragment-mm]
    import json
    import sys

    try:
        options = sys.argv[4:]
        option = next((value for value in options if not value.startswith("ids=")), None)
        target_ids_option = next((value for value in options if value.startswith("ids=")), None)
        selected_steps = (
            cast(tuple[RepairStep, ...], tuple(option.removeprefix("steps=").split(",")))
            if option and option.startswith("steps=")
            else None
        )
        result = RepairOutcome(
            ok=True,
            report=repair_file(
                Path(sys.argv[2]),
                sys.argv[1],
                Path(sys.argv[3]),
                fragment_max_size_mm=float(option) if option and selected_steps is None else None,
                steps=selected_steps,
                target_defect_ids=(
                    tuple(target_ids_option.removeprefix("ids=").split(","))
                    if target_ids_option
                    else None
                ),
            ),
            output_path=sys.argv[3],
        )
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        result = RepairOutcome(
            ok=False,
            error=RepairFailure(code="repair_failed", message=f"{type(exc).__name__}: {exc}"),
        )
    sys.stdout.write(json.dumps(result.model_dump(mode="json")))
