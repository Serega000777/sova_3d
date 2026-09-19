"""Per-printer calibration (T-126..T-128, F-028/F-029).

Every printer prints holes a little small and pegs a little big, and every machine by a
different amount. A calibration print is a coupon the kernel builds — holes of 3, 5 and
8 mm, pegs of 5 and 8 mm, a 60 mm edge — the user measures with calipers, and the numbers
come back as the profile's calibration: from then on every screw hole, fit and shrink the
platform proposes for that printer uses what was measured, not what is typical.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.execution import Job
from app.models.printing import PrinterProfile
from app.services import jobs, printing, projects
from app.services.authz import require_workspace_role

# The job that builds a plan the platform authored; the handler lives in app.jobs and
# imports this name, never the other way round (the API image has no worker package).
EXECUTE_PLAN_JOB = "execute_plan"

# The coupon: nominal sizes the user will measure (mm).
HOLES_MM = (3.0, 5.0, 8.0)
PEGS_MM = (5.0, 8.0)
LENGTH_MM = 60.0
PLATE = (LENGTH_MM, 30.0, 4.0)
PEG_HEIGHT_MM = 8.0


def coupon_plan() -> dict[str, Any]:
    """A deterministic OperationPlan for the calibration coupon."""
    width, depth, height = PLATE
    operations: list[dict[str, Any]] = [
        {
            "id": "body",
            "type": "create_box",
            "schema_version": 1,
            "width_mm": width,
            "depth_mm": depth,
            "height_mm": height,
        }
    ]
    xs = (10.0, 25.0, 45.0)
    for x, diameter in zip(xs, HOLES_MM, strict=True):
        operations.append(
            {
                "id": f"hole_{diameter:g}",
                "type": "add_hole",
                "schema_version": 1,
                "target": "body",
                "face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
                "position_mm": [x, 9.0],
                "diameter_mm": diameter,
            }
        )
    for x, diameter in zip((15.0, 40.0), PEGS_MM, strict=True):
        peg = f"peg_{diameter:g}"
        operations.append(
            {
                "id": peg,
                "type": "create_cylinder",
                "schema_version": 1,
                "diameter_mm": diameter,
                "height_mm": height + PEG_HEIGHT_MM,
                "axis": "z",
                "origin_mm": [x, 22.0, 0.0],
            }
        )
        operations.append(
            {
                "id": f"fuse_{peg}",
                "type": "boolean",
                "schema_version": 1,
                "op": "fuse",
                "target": "body",
                "tool": peg,
            }
        )
    return {
        "schema_version": 1,
        "goal": "Calibration coupon: holes 3/5/8 mm, pegs 5/8 mm, 60 mm edge",
        "assumptions": ["Print it flat, as modelled, in the material you calibrate for"],
        "operations": operations,
        "validation_steps": [
            f"plate {width:g} x {depth:g} x {height:g} mm",
            "three through holes and two pegs",
        ],
        "expected_outputs": ["body"],
    }


def coupon_features() -> list[dict[str, Any]]:
    """What to measure, for the form the clients show."""
    features = [
        {"id": f"hole_{d:g}_mm", "kind": "hole", "nominal_mm": d, "label": f"Hole Ø{d:g} mm"}
        for d in HOLES_MM
    ]
    features += [
        {"id": f"peg_{d:g}_mm", "kind": "peg", "nominal_mm": d, "label": f"Peg Ø{d:g} mm"}
        for d in PEGS_MM
    ]
    features.append(
        {
            "id": "length_60_mm",
            "kind": "length",
            "nominal_mm": LENGTH_MM,
            "label": f"Long edge {LENGTH_MM:g} mm",
        }
    )
    return features


class Measurements(BaseModel):
    """Caliper readings in mm; any subset — the rest simply is not learned."""

    hole_3_mm: float | None = Field(default=None, gt=0, lt=20)
    hole_5_mm: float | None = Field(default=None, gt=0, lt=20)
    hole_8_mm: float | None = Field(default=None, gt=0, lt=20)
    peg_5_mm: float | None = Field(default=None, gt=0, lt=20)
    peg_8_mm: float | None = Field(default=None, gt=0, lt=20)
    length_60_mm: float | None = Field(default=None, gt=0, lt=100)


class Calibration(BaseModel):
    """What the printer does to sizes, learned from the coupon."""

    hole_undersize_mm: float | None = None
    peg_oversize_mm: float | None = None
    # Half the difference: how far every outline is off, per side (positive = fat lines).
    xy_compensation_mm: float | None = None
    shrinkage_pct: float | None = None
    samples: int = 0
    measured_at: str | None = None
    measurements: dict[str, float] = Field(default_factory=dict)


def derive(measurements: Measurements) -> Calibration:
    """Rules of thumb from calipers: means of the differences, nothing cleverer."""
    given = {k: v for k, v in measurements.model_dump().items() if v is not None}
    if not given:
        raise ValidationFailedError("measure at least one feature of the coupon")
    holes = [
        nominal - given[f"hole_{nominal:g}_mm"]
        for nominal in HOLES_MM
        if f"hole_{nominal:g}_mm" in given
    ]
    pegs = [
        given[f"peg_{nominal:g}_mm"] - nominal
        for nominal in PEGS_MM
        if f"peg_{nominal:g}_mm" in given
    ]
    for value in (*holes, *pegs):
        if abs(value) > 2.0:
            raise ValidationFailedError(
                "a reading is more than 2 mm off its nominal — check the calipers",
                {"difference_mm": round(value, 3)},
            )
    calibration = Calibration(
        samples=len(given),
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        measurements={k: round(v, 3) for k, v in given.items()},
    )
    if holes:
        calibration.hole_undersize_mm = round(sum(holes) / len(holes), 3)
    if pegs:
        calibration.peg_oversize_mm = round(sum(pegs) / len(pegs), 3)
    if holes and pegs:
        assert calibration.hole_undersize_mm is not None
        assert calibration.peg_oversize_mm is not None
        calibration.xy_compensation_mm = round(
            (calibration.hole_undersize_mm + calibration.peg_oversize_mm) / 4, 3
        )
    if "length_60_mm" in given:
        calibration.shrinkage_pct = round((LENGTH_MM - given["length_60_mm"]) / LENGTH_MM * 100, 3)
    return calibration


def start_calibration_print(
    db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID
) -> tuple[PrinterProfile, Any, Job]:
    """A project with the coupon being built; print it, measure it, come back."""
    profile = printing.get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    project = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=profile.workspace_id,
        name=f"Calibration · {profile.name}",
        description="Print flat, measure the holes, pegs and the long edge with calipers.",
    )
    job = jobs.enqueue(
        db,
        workspace_id=profile.workspace_id,
        job_type=EXECUTE_PLAN_JOB,
        input={
            "project_id": str(project.id),
            "plan": coupon_plan(),
            "label": "Calibration coupon",
            "provenance": {"calibration_for_profile_id": str(profile.id)},
        },
        created_by=user_id,
        project_id=project.id,
    )
    return profile, project, job


def record_measurements(
    db: Session, *, user_id: uuid.UUID, profile_id: uuid.UUID, measurements: Measurements
) -> PrinterProfile:
    """The coupon's readings become the profile's calibration (merged, newest wins)."""
    profile = printing.get_profile(db, user_id=user_id, profile_id=profile_id)
    require_workspace_role(db, user_id, profile.workspace_id, WorkspaceRole.editor)
    learned = derive(measurements).model_dump(exclude_none=True)
    profile.calibration = {**(profile.calibration or {}), **learned}
    db.flush()
    return profile


def undersize_for(profile: PrinterProfile | None) -> float | None:
    """The measured hole undersize, when the profile has one."""
    if profile is None:
        return None
    value = (profile.calibration or {}).get("hole_undersize_mm")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
