"""Bounded metric fastener solids for reference 66.

The geometry is an exact smooth manufacturing envelope: a nominal shank and a selected
head joined into one CAD solid. Threads and drive recesses remain metadata because the
platform does not yet model external threads or torque/contact mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.engineering import knowledge as kb
from app.geometry.operations import OperationPlan, parse_plan

FastenerHead = Literal["socket_cap", "pan", "countersunk"]
FastenerDrive = Literal["hex", "phillips", "torx"]


@dataclass(frozen=True, slots=True)
class FastenerEnvelope:
    size: str
    nominal_mm: float
    length_mm: float
    head: FastenerHead
    drive: FastenerDrive
    head_diameter_mm: float
    head_height_mm: float

    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "size": self.size,
            "nominal_mm": self.nominal_mm,
            "length_mm": self.length_mm,
            "head": self.head,
            "drive": self.drive,
            "head_diameter_mm": self.head_diameter_mm,
            "head_height_mm": self.head_height_mm,
            "thread_geometry": "smooth_nominal_envelope",
            "drive_recess_modeled": False,
            "geometry_reference": "head_seat_z0",
        }


def envelope(
    *, size: str, length_mm: float, head: FastenerHead, drive: FastenerDrive
) -> FastenerEnvelope:
    known = kb.FASTENERS.get(size.casefold())
    if known is None:
        raise ValueError(f"unknown metric fastener {size!r}")
    if not 2 <= length_mm <= 200:
        raise ValueError("fastener length must be between 2 and 200 mm")
    if head == "socket_cap":
        head_diameter = known.head_mm
        head_height = known.nominal_mm
    elif head == "pan":
        head_diameter = round(known.nominal_mm * 1.9, 3)
        head_height = round(known.nominal_mm * 0.65, 3)
    else:
        head_diameter = round(known.nominal_mm * 2.0, 3)
        head_height = round(known.nominal_mm * 0.5, 3)
    return FastenerEnvelope(
        size=known.name,
        nominal_mm=known.nominal_mm,
        length_mm=round(length_mm, 3),
        head=head,
        drive=drive,
        head_diameter_mm=head_diameter,
        head_height_mm=head_height,
    )


def plan_for(spec: FastenerEnvelope) -> OperationPlan:
    # The shank overlaps the head by 0.1 mm so OCCT performs a real fuse instead of a
    # coincident-face join. The public length remains measured from the z=0 head seat.
    operations: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "id": "shank",
            "type": "create_cylinder",
            "diameter_mm": spec.nominal_mm,
            "height_mm": spec.length_mm + 0.1,
            "axis": "z",
            "origin_mm": [0.0, 0.0, -spec.length_mm],
        }
    ]
    if spec.head == "countersunk":
        operations.append(
            {
                "schema_version": 1,
                "id": "head",
                "type": "create_cone",
                "bottom_diameter_mm": spec.nominal_mm,
                "top_diameter_mm": spec.head_diameter_mm,
                "height_mm": spec.head_height_mm,
                "axis": "z",
                "origin_mm": [0.0, 0.0, 0.0],
            }
        )
    else:
        operations.append(
            {
                "schema_version": 1,
                "id": "head",
                "type": "create_cylinder",
                "diameter_mm": spec.head_diameter_mm,
                "height_mm": spec.head_height_mm,
                "axis": "z",
                "origin_mm": [0.0, 0.0, 0.0],
            }
        )
    operations.append(
        {
            "schema_version": 1,
            "id": "join_head",
            "type": "boolean",
            "op": "fuse",
            "target": "shank",
            "tool": "head",
        }
    )
    return parse_plan(
        {
            "schema_version": 1,
            "goal": f"{spec.size}×{spec.length_mm:g} {spec.head.replace('_', ' ')} fastener",
            "assumptions": [
                "smooth nominal shank envelope; external thread is not modeled",
                "drive type is retained as metadata; the recess is not cut into the head",
            ],
            "operations": operations,
            "validation_steps": [
                "one closed exact solid",
                "head seat remains at z=0 and shank extends in negative z",
            ],
            "expected_outputs": ["shank"],
        }
    )
