"""Parametric quick-start shell for a house-design project."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from app.geometry.operations import OperationPlan

HouseShape = Literal["rectangle", "l_shape", "t_shape"]
HouseLength = Annotated[float, Field(ge=2_000, le=50_000)]
FloorHeight = Annotated[float, Field(ge=2_200, le=6_000)]
FloorCount = Annotated[int, Field(ge=1, le=3)]
StairWidth = Annotated[float, Field(ge=700, le=2_000)]
StairTread = Annotated[float, Field(ge=200, le=400)]
StairSteps = Annotated[int, Field(ge=10, le=30)]
StairPlacement = Literal["left", "center", "right"]


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class StraightStairRequest:
    """One bounded straight flight repeated between adjacent floors.

    The floor height remains authoritative on ``HouseBoxRequest``.  Rise is derived from it
    instead of accepting two contradictory dimensions from a client.
    """

    width_mm: StairWidth = 1_000
    tread_depth_mm: StairTread = 280
    step_count: StairSteps = 17
    placement: StairPlacement = "center"
    railing: bool = True
    material_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class HouseBoxRequest:
    length_mm: HouseLength
    width_mm: HouseLength
    floor_height_mm: FloorHeight
    floors: FloorCount
    shape: HouseShape = "rectangle"
    stair: StraightStairRequest | None = None

    def __post_init__(self) -> None:
        if self.stair is None:
            return
        if self.floors < 2:
            raise ValueError("a stair requires at least two floors")
        if self.shape != "rectangle":
            raise ValueError("the bounded stair builder currently requires a rectangular house")
        rise = float(self.floor_height_mm) / self.stair.step_count
        if not 120 <= rise <= 220:
            raise ValueError("floor height divided by step count must produce a 120-220 mm rise")
        _stair_origin(self)

    def build(self) -> OperationPlan:
        return build(self)


def _box(
    op_id: str,
    *,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "create_box",
        "schema_version": 1,
        "width_mm": width_mm,
        "depth_mm": depth_mm,
        "height_mm": height_mm,
        "origin_mm": origin_mm,
    }


def _fuse(op_id: str, *, target: str, tool: str) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "boolean",
        "schema_version": 1,
        "op": "fuse",
        "target": target,
        "tool": tool,
    }


def _stair_origin(request: HouseBoxRequest) -> tuple[float, float]:
    """Return a trusted in-footprint origin or reject an impossible stair/shaft."""
    if request.stair is None:  # pragma: no cover - callers prove this first
        raise ValueError("the house has no stair")
    wall = 250.0
    clearance = wall + 100.0
    run = float(request.stair.tread_depth_mm) * request.stair.step_count
    width = float(request.stair.width_mm)
    x = (float(request.length_mm) - run) / 2
    if request.stair.placement == "left":
        y = clearance
    elif request.stair.placement == "right":
        y = float(request.width_mm) - clearance - width
    else:
        y = (float(request.width_mm) - width) / 2
    if (
        x < clearance
        or x + run > float(request.length_mm) - clearance
        or y < clearance
        or y + width > float(request.width_mm) - clearance
    ):
        raise ValueError("the stair and its opening do not fit inside the house footprint")
    return x, y


def _multifloor_operations(request: HouseBoxRequest) -> tuple[list[dict[str, object]], list[str]]:
    """Build separate floor shells and exact stair flights for scene-level visibility."""
    assert request.stair is not None
    length = float(request.length_mm)
    width = float(request.width_mm)
    floor_height = float(request.floor_height_mm)
    stair = request.stair
    tread = float(stair.tread_depth_mm)
    stair_width = float(stair.width_mm)
    rise = floor_height / stair.step_count
    run = tread * stair.step_count
    x, y = _stair_origin(request)
    wall = 250.0
    opening_margin = 50.0
    operations: list[dict[str, object]] = []
    outputs: list[str] = []

    for floor_index in range(request.floors):
        floor_id = f"floor_{floor_index + 1}"
        z = floor_index * floor_height
        operations.extend(
            [
                _box(
                    floor_id,
                    width_mm=length,
                    depth_mm=width,
                    height_mm=floor_height,
                    origin_mm=(0.0, 0.0, z),
                ),
                {
                    "id": f"hollow_{floor_id}",
                    "type": "shell",
                    "schema_version": 1,
                    "target": floor_id,
                    "thickness_mm": wall,
                    "open_face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
                },
            ]
        )
        if floor_index > 0:
            opening_id = f"stair_opening_{floor_index + 1}"
            operations.extend(
                [
                    _box(
                        opening_id,
                        width_mm=run + 2 * opening_margin,
                        depth_mm=stair_width + 2 * opening_margin,
                        height_mm=wall + 2,
                        origin_mm=(x - opening_margin, y - opening_margin, z - 1),
                    ),
                    {
                        "id": f"cut_{opening_id}",
                        "type": "boolean",
                        "schema_version": 1,
                        "op": "cut",
                        "target": floor_id,
                        "tool": opening_id,
                    },
                ]
            )
        outputs.append(floor_id)

    operations.append(
        _box(
            "roof",
            width_mm=length,
            depth_mm=width,
            height_mm=wall,
            origin_mm=(0.0, 0.0, request.floors * floor_height),
        )
    )
    outputs.append("roof")

    for floor_index in range(request.floors - 1):
        z = floor_index * floor_height
        flight_id = f"stair_{floor_index + 1}_{floor_index + 2}"
        first_step = f"{flight_id}_step_1"
        for step_index in range(stair.step_count):
            step_id = f"{flight_id}_step_{step_index + 1}"
            operations.append(
                _box(
                    step_id,
                    width_mm=tread,
                    depth_mm=stair_width,
                    height_mm=rise * (step_index + 1),
                    origin_mm=(x + tread * step_index, y, z),
                )
            )
            if step_index:
                operations.append(
                    _fuse(
                        f"join_{flight_id}_step_{step_index + 1}",
                        target=first_step,
                        tool=step_id,
                    )
                )
        outputs.append(first_step)
        if stair.railing:
            angle = -math.degrees(math.atan2(floor_height, run))
            rail_length = math.hypot(run, floor_height)
            for side, rail_y in (("left", y), ("right", y + stair_width - 50.0)):
                rail_id = f"rail_{side}_{floor_index + 1}_{floor_index + 2}"
                rail_z = z + 900.0
                operations.extend(
                    [
                        _box(
                            rail_id,
                            width_mm=rail_length,
                            depth_mm=50.0,
                            height_mm=50.0,
                            origin_mm=(x, rail_y, rail_z),
                        ),
                        {
                            "id": f"slope_{rail_id}",
                            "type": "rotate",
                            "schema_version": 1,
                            "target": rail_id,
                            "axis": "y",
                            "angle_deg": angle,
                            "origin_mm": (x, rail_y, rail_z),
                        },
                    ]
                )
                outputs.append(rail_id)
    return operations, outputs


def build(request: HouseBoxRequest) -> OperationPlan:
    """Build a single solid whose bounding box matches the requested house dimensions."""
    length = float(request.length_mm)
    width = float(request.width_mm)
    height = float(request.floor_height_mm) * request.floors

    if request.stair is not None:
        operations, outputs = _multifloor_operations(request)
        return OperationPlan.model_validate(
            {
                "schema_version": 1,
                "goal": f"{request.floors}-floor house with a straight stair",
                "assumptions": [
                    "All dimensions are millimetres.",
                    "Each floor is a separate exact shell so floor visibility is deterministic.",
                    (
                        "The straight flight and upper-floor openings are generated from one "
                        "stair spec."
                    ),
                ],
                "operations": operations,
                "validation_steps": [
                    "Confirm every floor shell is a valid solid.",
                    "Confirm every upper floor has one opening aligned to the stair flight.",
                    "Confirm the top step reaches the exact floor-to-floor height.",
                ],
                "expected_outputs": outputs,
            }
        )

    if request.shape == "rectangle":
        operations = [_box("house", width_mm=length, depth_mm=width, height_mm=height)]
    elif request.shape == "l_shape":
        operations = [
            _box("house", width_mm=length, depth_mm=width / 2, height_mm=height),
            _box("side_wing", width_mm=length / 2, depth_mm=width, height_mm=height),
            _fuse("join_side_wing", target="house", tool="side_wing"),
        ]
    else:
        third = length / 3
        overlap = min(10.0, third / 100)
        operations = [
            _box(
                "house",
                width_mm=third,
                depth_mm=width,
                height_mm=height,
                origin_mm=(third, 0.0, 0.0),
            ),
            _box(
                "left_wing",
                width_mm=third + overlap,
                depth_mm=width / 3,
                height_mm=height,
                origin_mm=(0.0, width * 2 / 3, 0.0),
            ),
            _box(
                "right_wing",
                width_mm=third + overlap,
                depth_mm=width / 3,
                height_mm=height,
                origin_mm=(length - third - overlap, width * 2 / 3, 0.0),
            ),
            _fuse("join_left_wing", target="house", tool="left_wing"),
            _fuse("join_right_wing", target="house", tool="right_wing"),
        ]

    return OperationPlan.model_validate(
        {
            "schema_version": 1,
            "goal": f"{request.floors}-floor {request.shape} house massing box",
            "assumptions": [
                "All dimensions are millimetres.",
                "The result is a solid massing box; rooms, walls and openings are not generated.",
            ],
            "operations": operations,
            "validation_steps": [
                "Confirm the solid bounding box matches length, width and total floor height.",
                "Confirm compound shapes form one fused solid.",
            ],
            "expected_outputs": ["house"],
        }
    )
