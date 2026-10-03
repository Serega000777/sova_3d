"""Parametric quick-start shell for a house-design project."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from app.geometry.operations import OperationPlan

HouseShape = Literal["rectangle", "l_shape", "t_shape"]
HouseLength = Annotated[float, Field(ge=2_000, le=50_000)]
FloorHeight = Annotated[float, Field(ge=2_200, le=6_000)]
FloorCount = Annotated[int, Field(ge=1, le=3)]


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class HouseBoxRequest:
    length_mm: HouseLength
    width_mm: HouseLength
    floor_height_mm: FloorHeight
    floors: FloorCount
    shape: HouseShape = "rectangle"

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


def build(request: HouseBoxRequest) -> OperationPlan:
    """Build a single solid whose bounding box matches the requested house dimensions."""
    length = float(request.length_mm)
    width = float(request.width_mm)
    height = float(request.floor_height_mm) * request.floors

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
                "house", width_mm=third, depth_mm=width, height_mm=height,
                origin_mm=(third, 0.0, 0.0),
            ),
            _box(
                "left_wing", width_mm=third + overlap, depth_mm=width / 3,
                height_mm=height, origin_mm=(0.0, width * 2 / 3, 0.0),
            ),
            _box(
                "right_wing", width_mm=third + overlap, depth_mm=width / 3,
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
