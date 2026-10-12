"""Exact, bounded empty-room shell derived only from validated RoomPlan v2 geometry."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import cast

from app.engineering.room_plan import RoomPlanCapture, RoomPlanConversion
from app.geometry.operations import OperationPlan

FLOOR_THICKNESS_MM = 20.0
WALL_THICKNESS_MM = 120.0
MAX_SHELL_OPERATIONS = 256


@dataclass(frozen=True, slots=True)
class RoomShellOpening:
    wall: int
    offset_mm: float
    width_mm: float
    bottom_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class RoomShellSpec:
    outline_mm: tuple[tuple[float, float], ...]
    wall_height_mm: float
    openings: tuple[RoomShellOpening, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "outline_mm": [list(point) for point in self.outline_mm],
            "wall_height_mm": self.wall_height_mm,
            "floor_thickness_mm": FLOOR_THICKNESS_MM,
            "wall_thickness_mm": WALL_THICKNESS_MM,
            "openings": [asdict(opening) for opening in self.openings],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> RoomShellSpec:
        outline = cast(list[list[float]], value["outline_mm"])
        openings = cast(list[dict[str, int | float]], value.get("openings", []))
        return cls(
            outline_mm=tuple((float(point[0]), float(point[1])) for point in outline),
            wall_height_mm=float(cast(float, value["wall_height_mm"])),
            openings=tuple(
                RoomShellOpening(
                    wall=int(item["wall"]),
                    offset_mm=float(item["offset_mm"]),
                    width_mm=float(item["width_mm"]),
                    bottom_mm=float(item["bottom_mm"]),
                    height_mm=float(item["height_mm"]),
                )
                for item in openings
            ),
        )


def room_shell_spec(
    capture: RoomPlanCapture, conversion: RoomPlanConversion
) -> RoomShellSpec | None:
    if capture.schema_version != 2:
        return None
    plan = conversion.plan
    wall_height_mm = conversion.floor_height_mm
    outline = tuple(
        (
            float(point[0]) + conversion.source_origin_mm[0],
            float(point[1]) + conversion.source_origin_mm[1],
        )
        for point in plan.rooms[0].outline
    )
    if len(outline) != len(plan.walls) or len(conversion.wall_ids) != len(plan.walls):
        raise ValueError("RoomPlan shell requires one simple wall loop")
    walls_by_id = {wall.identifier: wall for wall in capture.walls}
    for index, wall_id in enumerate(conversion.wall_ids):
        source_wall = walls_by_id[wall_id]
        if source_wall.dimensions_m is None:
            raise ValueError(f"RoomPlan v2 wall {wall_id} has no dimensions")
        measured_length = math.hypot(
            plan.walls[index].b[0] - plan.walls[index].a[0],
            plan.walls[index].b[1] - plan.walls[index].a[1],
        )
        if abs(source_wall.dimensions_m[0] * 1_000 - measured_length) > 20:
            raise ValueError(f"RoomPlan wall {wall_id} width disagrees with its endpoints")
        if abs(source_wall.dimensions_m[1] * 1_000 - source_wall.height_m * 1_000) > 20:
            raise ValueError(f"RoomPlan wall {wall_id} height is inconsistent")
    source_by_id = {opening.identifier: opening for opening in capture.openings}
    if len(conversion.opening_ids) != len(plan.openings):
        raise ValueError("RoomPlan shell opening lineage is incomplete")
    shell_openings: list[RoomShellOpening] = []
    for opening, source_id in zip(plan.openings, conversion.opening_ids, strict=True):
        source = source_by_id.get(source_id)
        if source is None or source.transform_m is None or source.dimensions_m is None:
            raise ValueError("RoomPlan v2 opening could not be associated with its parent wall")
        if source.parent_wall_id != conversion.wall_ids[opening.wall]:
            raise ValueError("RoomPlan opening parent changed during shell conversion")
        if abs(source.dimensions_m[0] * 1_000 - opening.width_mm) > 20:
            raise ValueError(f"RoomPlan opening {source.identifier} width is inconsistent")
        if (
            math.hypot(
                source.transform_m[12] - source.center_m[0],
                source.transform_m[14] - source.center_m[1],
            )
            > 0.02
        ):
            raise ValueError(f"RoomPlan opening {source.identifier} transform is inconsistent")
        center_y_mm = float(source.transform_m[13]) * 1_000
        height_mm = float(source.dimensions_m[1]) * 1_000
        bottom_mm = center_y_mm - height_mm / 2
        if bottom_mm < -50 or bottom_mm + height_mm > wall_height_mm + 50:
            raise ValueError(f"RoomPlan opening {source.identifier} lies outside its wall height")
        shell_openings.append(
            RoomShellOpening(
                wall=opening.wall,
                offset_mm=float(opening.offset_mm),
                width_mm=float(opening.width_mm),
                bottom_mm=max(0.0, bottom_mm),
                height_mm=min(height_mm, wall_height_mm - max(0.0, bottom_mm)),
            )
        )
    for wall in range(len(plan.walls)):
        intervals = sorted(
            (item.offset_mm, item.offset_mm + item.width_mm)
            for item in shell_openings
            if item.wall == wall
        )
        if any(
            current[0] < previous[1] - 1
            for previous, current in zip(intervals, intervals[1:], strict=False)
        ):
            raise ValueError("RoomPlan openings overlap on one wall")
    return RoomShellSpec(outline, float(wall_height_mm), tuple(shell_openings))


def build_room_shell_plan(spec: RoomShellSpec) -> OperationPlan:
    operations: list[dict[str, object]] = [
        {
            "id": "floor",
            "type": "extrude",
            "schema_version": 1,
            "profile": {"kind": "polygon", "points_mm": spec.outline_mm},
            "height_mm": FLOOR_THICKNESS_MM,
            "origin_mm": (0.0, 0.0, -FLOOR_THICKNESS_MM),
        }
    ]
    for index, (a, b) in enumerate(
        zip(spec.outline_mm, spec.outline_mm[1:] + spec.outline_mm[:1], strict=True)
    ):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        wall = f"wall_{index}"
        operations.extend(
            [
                {
                    "id": wall,
                    "type": "create_box",
                    "schema_version": 1,
                    "width_mm": length,
                    "depth_mm": WALL_THICKNESS_MM,
                    "height_mm": spec.wall_height_mm,
                    "origin_mm": (0.0, -WALL_THICKNESS_MM / 2, 0.0),
                },
                {
                    "id": f"{wall}_rot",
                    "type": "rotate",
                    "schema_version": 1,
                    "target": wall,
                    "axis": "z",
                    "angle_deg": angle,
                    "origin_mm": (0.0, 0.0, 0.0),
                },
                {
                    "id": f"{wall}_pos",
                    "type": "translate",
                    "schema_version": 1,
                    "target": wall,
                    "offset_mm": (a[0], a[1], 0.0),
                },
            ]
        )
        for opening_index, opening in enumerate(
            item for item in spec.openings if item.wall == index
        ):
            cutter = f"opening_{index}_{opening_index}"
            operations.extend(
                [
                    {
                        "id": cutter,
                        "type": "create_box",
                        "schema_version": 1,
                        "width_mm": opening.width_mm,
                        "depth_mm": WALL_THICKNESS_MM + 2,
                        "height_mm": opening.height_mm,
                        "origin_mm": (
                            opening.offset_mm,
                            -WALL_THICKNESS_MM / 2 - 1,
                            opening.bottom_mm,
                        ),
                    },
                    {
                        "id": f"{cutter}_rot",
                        "type": "rotate",
                        "schema_version": 1,
                        "target": cutter,
                        "axis": "z",
                        "angle_deg": angle,
                        "origin_mm": (0.0, 0.0, 0.0),
                    },
                    {
                        "id": f"{cutter}_pos",
                        "type": "translate",
                        "schema_version": 1,
                        "target": cutter,
                        "offset_mm": (a[0], a[1], 0.0),
                    },
                    {
                        "id": f"cut_{cutter}",
                        "type": "boolean",
                        "schema_version": 1,
                        "op": "cut",
                        "target": wall,
                        "tool": cutter,
                    },
                ]
            )
        operations.append(
            {
                "id": f"join_{wall}",
                "type": "boolean",
                "schema_version": 1,
                "op": "fuse",
                "target": "floor",
                "tool": wall,
            }
        )
    if len(operations) > MAX_SHELL_OPERATIONS:
        raise ValueError("RoomPlan shell exceeds the exact-kernel operation limit")
    return OperationPlan.model_validate(
        {
            "schema_version": 1,
            "goal": "Build an exact empty-room shell from validated RoomPlan v2 surfaces",
            "assumptions": [
                "All dimensions are millimetres.",
                "Furniture and captured surface noise are intentionally omitted.",
            ],
            "operations": operations,
            "validation_steps": [
                "Confirm one floor and one wall per perimeter edge.",
                "Confirm every opening remains inside its parent wall.",
            ],
            "expected_outputs": ["floor"],
        }
    )
