"""Conversion integrity report (T-023, F-015) and the printable gate (T-026, F-076).

Machine part: a list of typed checks with expected/actual/tolerance.
User part: `summary` — one plain sentence per problem, no jargon.
Tolerances depend on format semantics (docs/07 §2): mesh->mesh exports
must preserve geometry exactly; scene formats may legitimately change
vertex counts, so those checks are only applied where they mean something.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from worker.report import ImportMetadata, Severity

SCHEMA_VERSION: Literal[1] = 1


class CheckStatus(enum.StrEnum):
    passed = "pass"
    warned = "warn"
    failed = "fail"


class Check(BaseModel):
    id: str
    status: CheckStatus
    message: str
    expected: float | int | str | bool | None = None
    actual: float | int | str | bool | None = None
    tolerance: float | None = None


class GeometrySummary(BaseModel):
    format: str
    bbox_size_mm: tuple[float, float, float] | None
    faces: int | None
    vertices: int | None
    watertight: bool | None
    volume_mm3: float | None
    surface_area_mm2: float | None
    material_count: int | None = None


class IntegrityReport(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    source_format: str
    target_format: str
    printable_gate: bool
    status: CheckStatus
    checks: list[Check] = Field(default_factory=list)
    summary: str
    source: GeometrySummary
    output: GeometrySummary

    @property
    def ok(self) -> bool:
        return self.status is not CheckStatus.failed


# --- building ---------------------------------------------------------------------------------

REL_TOL_EXACT = 1e-6  # mesh->mesh with identical tessellation
REL_TOL_SCENE = 1e-4  # scene formats: float32 buffers, unit rescale
_EXACT_TESSELLATION = frozenset(
    {("stl", "stl"), ("obj", "stl"), ("stl", "obj"), ("obj", "obj"), ("stl", "3mf"), ("3mf", "stl")}
)


def summarize(meta: ImportMetadata) -> GeometrySummary:
    mesh = meta.mesh
    return GeometrySummary(
        format=meta.format,
        bbox_size_mm=meta.bbox.size if meta.bbox else None,
        faces=mesh.faces if mesh else None,
        vertices=mesh.vertices if mesh else None,
        watertight=mesh.watertight if mesh else None,
        volume_mm3=mesh.volume_mm3 if mesh else None,
        surface_area_mm2=mesh.surface_area_mm2 if mesh else None,
        material_count=meta.scene.materials if meta.scene else None,
    )


def build_report(
    source: ImportMetadata, output: ImportMetadata, *, printable_gate: bool
) -> IntegrityReport:
    checks: list[Check] = []
    pair = (source.format, output.format)
    rel_tol = REL_TOL_EXACT if pair in _EXACT_TESSELLATION else REL_TOL_SCENE

    checks.append(_coordinates_finite(output))
    checks.append(_bbox_check(source, output, rel_tol))
    if source.mesh and output.mesh:
        checks.append(
            _area_check(source.mesh.surface_area_mm2, output.mesh.surface_area_mm2, rel_tol)
        )
        if source.mesh.volume_mm3 is not None:
            checks.append(_volume_check(source.mesh.volume_mm3, output.mesh.volume_mm3, rel_tol))
        checks.append(_watertight_check(source.mesh.watertight, output.mesh.watertight))
        if pair in _EXACT_TESSELLATION:
            checks.append(
                _equal_check("face_count", "triangle count", source.mesh.faces, output.mesh.faces)
            )
    if source.scene and output.scene:
        checks.append(
            _equal_check(
                "material_count", "material count", source.scene.materials, output.scene.materials
            )
        )
    checks.append(_units_check(output))
    if printable_gate:
        checks.append(_printable_check(output))

    status = _overall(checks)
    problems = [c.message for c in checks if c.status is not CheckStatus.passed]
    summary = (
        f"{source.format.upper()} → {output.format.upper()}: geometry preserved."
        if not problems
        else f"{source.format.upper()} → {output.format.upper()}: " + " ".join(problems)
    )
    return IntegrityReport(
        source_format=source.format,
        target_format=output.format,
        printable_gate=printable_gate,
        status=status,
        checks=checks,
        summary=summary,
        source=summarize(source),
        output=summarize(output),
    )


def _overall(checks: list[Check]) -> CheckStatus:
    if any(c.status is CheckStatus.failed for c in checks):
        return CheckStatus.failed
    if any(c.status is CheckStatus.warned for c in checks):
        return CheckStatus.warned
    return CheckStatus.passed


def _rel_diff(a: float, b: float) -> float:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale


def _coordinates_finite(output: ImportMetadata) -> Check:
    bad = any(w.code == "nan_coordinates" for w in output.warnings)
    return Check(
        id="coordinates_finite",
        status=CheckStatus.failed if bad else CheckStatus.passed,
        message="The exported file contains invalid (NaN/infinite) coordinates."
        if bad
        else "All coordinates are finite.",
    )


def _bbox_check(source: ImportMetadata, output: ImportMetadata, tol: float) -> Check:
    if source.bbox is None or output.bbox is None:
        return Check(
            id="bbox_size",
            status=CheckStatus.failed,
            message="Could not compare overall dimensions.",
        )
    diff = max(_rel_diff(a, b) for a, b in zip(source.bbox.size, output.bbox.size, strict=True))
    ok = diff <= tol
    return Check(
        id="bbox_size",
        status=CheckStatus.passed if ok else CheckStatus.failed,
        message="Overall dimensions are preserved."
        if ok
        else "Overall dimensions changed during conversion.",
        expected=_fmt_size(source.bbox.size),
        actual=_fmt_size(output.bbox.size),
        tolerance=tol,
    )


def _fmt_size(size: tuple[float, float, float]) -> str:
    return f"{size[0]:.4f}x{size[1]:.4f}x{size[2]:.4f} mm"


def _area_check(expected: float, actual: float, tol: float) -> Check:
    ok = _rel_diff(expected, actual) <= tol
    return Check(
        id="surface_area",
        status=CheckStatus.passed if ok else CheckStatus.warned,
        message="Surface area is preserved." if ok else "Surface area changed during conversion.",
        expected=round(expected, 6),
        actual=round(actual, 6),
        tolerance=tol,
    )


def _volume_check(expected: float, actual: float | None, tol: float) -> Check:
    if actual is None:
        return Check(
            id="volume",
            status=CheckStatus.failed,
            message="The export is no longer a closed solid, so its volume is undefined.",
            expected=round(expected, 6),
            actual=None,
        )
    ok = _rel_diff(expected, actual) <= tol
    return Check(
        id="volume",
        status=CheckStatus.passed if ok else CheckStatus.failed,
        message="Volume is preserved." if ok else "Volume changed during conversion.",
        expected=round(expected, 6),
        actual=round(actual, 6),
        tolerance=tol,
    )


def _watertight_check(expected: bool, actual: bool) -> Check:
    if expected and not actual:
        return Check(
            id="watertight",
            status=CheckStatus.failed,
            message="The source was watertight but the export has open edges.",
            expected=True,
            actual=False,
        )
    return Check(
        id="watertight",
        status=CheckStatus.passed,
        message="Watertightness is preserved." if expected else "Source was not watertight.",
        expected=expected,
        actual=actual,
    )


def _equal_check(check_id: str, label: str, expected: int, actual: int) -> Check:
    ok = expected == actual
    return Check(
        id=check_id,
        status=CheckStatus.passed if ok else CheckStatus.warned,
        message=f"The {label} is preserved."
        if ok
        else f"The {label} changed ({expected} → {actual}).",
        expected=expected,
        actual=actual,
    )


def _units_check(output: ImportMetadata) -> Check:
    explicit = output.unit_source == "file"
    return Check(
        id="units_explicit",
        status=CheckStatus.passed if explicit else CheckStatus.warned,
        message="The file declares its units."
        if explicit
        else f"{output.format.upper()} cannot store units; millimetres are assumed on import.",
        actual=output.source_units or "assumed mm",
    )


def _printable_check(output: ImportMetadata) -> Check:
    mesh = output.mesh
    reasons: list[str] = []
    if mesh is None or mesh.faces == 0:
        reasons.append("no geometry")
    else:
        if not mesh.watertight:
            reasons.append("open edges")
        if not mesh.winding_consistent:
            reasons.append("inconsistent face orientation")
        if mesh.degenerate_faces:
            reasons.append(f"{mesh.degenerate_faces} zero-area faces")
    if any(w.severity is Severity.error for w in output.warnings):
        reasons.append("invalid coordinates")
    if any(w.code == "zero_extent" for w in output.warnings):
        reasons.append("zero thickness")
    if reasons:
        return Check(
            id="printable_topology",
            status=CheckStatus.failed,
            message="Not print-ready: " + ", ".join(reasons) + ". Run Repair before exporting.",
            actual=", ".join(reasons),
        )
    return Check(
        id="printable_topology",
        status=CheckStatus.passed,
        message="The model is a closed, consistently oriented solid.",
        actual="manifold",
    )


if __name__ == "__main__":  # `python -m worker.integrity --emit-schema` refreshes the contract
    import json
    import sys

    if "--emit-schema" in sys.argv:
        contracts = Path(__file__).resolve().parents[3] / "packages" / "contracts"
        target = contracts / "integrity-report.schema.json"
        payload = json.dumps(IntegrityReport.model_json_schema(), indent=2) + "\n"
        target.write_text(payload, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
