"""Exact rectangular-house facade editor built from existing kernel operations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass
from pydantic_core import ArgsKwargs

from app.geometry.operations import OperationPlan

FacadeSide = Literal["front", "back", "left", "right"]
OpeningKind = Literal["window", "door"]
RoofKind = Literal["none", "flat", "gable"]

# OperationPlan allows 256 operations: the wall box and its shell take two, each opening a
# cutter box plus a boolean cut, and a flat or gable roof a solid plus a fuse. 2 + 2n + 2 <= 256
# gives a ceiling that holds for every roof kind.
MAX_PLAN_OPERATIONS = 256
MAX_OPENINGS = (MAX_PLAN_OPERATIONS - 4) // 2


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class FacadeOpening:
    kind: OpeningKind
    side: FacadeSide
    center_mm: Annotated[float, Field(ge=100, le=49_900)]
    width_mm: Annotated[float, Field(ge=300, le=5_000)]
    height_mm: Annotated[float, Field(ge=300, le=5_000)]
    sill_mm: Annotated[float, Field(ge=0, le=15_000)] = 900

    @model_validator(mode="before")
    @classmethod
    def doors_default_to_floor(cls, data: Any) -> Any:
        """Doors are cut from floor level: an omitted door sill is 0, never the window 900."""
        fields = data.kwargs if isinstance(data, ArgsKwargs) else data
        if not isinstance(fields, dict) or fields.get("kind") != "door":
            return data
        if fields.get("sill_mm") is not None:
            return data
        fields = {**fields, "sill_mm": 0}
        return ArgsKwargs(data.args, fields) if isinstance(data, ArgsKwargs) else fields

    @model_validator(mode="after")
    def doors_start_at_floor(self) -> FacadeOpening:
        if self.kind == "door" and self.sill_mm != 0:
            raise ValueError("doors start at floor level; omit sill_mm or send 0")
        return self


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class FacadeRequest:
    length_mm: Annotated[float, Field(ge=2_000, le=50_000)]
    width_mm: Annotated[float, Field(ge=2_000, le=50_000)]
    floor_height_mm: Annotated[float, Field(ge=2_200, le=6_000)]
    floors: Annotated[int, Field(ge=1, le=3)]
    wall_thickness_mm: Annotated[float, Field(ge=100, le=600)] = 250
    roof: RoofKind = "flat"
    roof_height_mm: Annotated[float, Field(ge=200, le=5_000)] = 1_200
    overhang_mm: Annotated[float, Field(ge=0, le=2_000)] = 300
    openings: list[FacadeOpening] = Field(default_factory=list, max_length=MAX_OPENINGS)

    @model_validator(mode="after")
    def openings_fit_facades(self) -> FacadeRequest:
        total_height = self.floor_height_mm * self.floors
        if self.roof != "none" and (
            self.length_mm + self.overhang_mm * 2 > 50_000
            or self.width_mm + self.overhang_mm * 2 > 50_000
        ):
            raise ValueError("roof including overhang must fit the 50000mm box bound")
        if self.roof == "gable" and self.width_mm + self.overhang_mm * 2 > 10_000:
            raise ValueError("gable roof span including overhang must be at most 10000mm")
        for index, opening in enumerate(self.openings):
            span = self.length_mm if opening.side in ("front", "back") else self.width_mm
            if (
                opening.center_mm - opening.width_mm / 2 < 0
                or opening.center_mm + opening.width_mm / 2 > span
            ):
                raise ValueError(f"opening {index} exceeds the {opening.side} facade width")
            if opening.sill_mm + opening.height_mm > total_height:
                raise ValueError(f"opening {index} exceeds the facade height")
        return self

    def build(self) -> OperationPlan:
        height = self.floor_height_mm * self.floors
        operations: list[dict[str, object]] = [
            {
                "id": "house",
                "type": "create_box",
                "schema_version": 1,
                "width_mm": self.length_mm,
                "depth_mm": self.width_mm,
                "height_mm": height,
            },
            {
                "id": "hollow_house",
                "type": "shell",
                "schema_version": 1,
                "target": "house",
                "thickness_mm": self.wall_thickness_mm,
                "open_face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            },
        ]
        margin = 2.0
        for index, opening in enumerate(self.openings, start=1):
            cutter = f"opening_{index}"
            # A door cut dips below the floor so it opens the wall's bottom face cleanly.
            z = opening.sill_mm - margin if opening.kind == "door" else opening.sill_mm
            cut_height = opening.height_mm + (margin if opening.kind == "door" else 0)
            if opening.side in ("front", "back"):
                origin = (
                    opening.center_mm - opening.width_mm / 2,
                    -margin
                    if opening.side == "front"
                    else self.width_mm - self.wall_thickness_mm - margin,
                    z,
                )
                size = (opening.width_mm, self.wall_thickness_mm + margin * 2, cut_height)
            else:
                origin = (
                    -margin
                    if opening.side == "left"
                    else self.length_mm - self.wall_thickness_mm - margin,
                    opening.center_mm - opening.width_mm / 2,
                    z,
                )
                size = (self.wall_thickness_mm + margin * 2, opening.width_mm, cut_height)
            operations.extend(
                [
                    {
                        "id": cutter,
                        "type": "create_box",
                        "schema_version": 1,
                        "width_mm": size[0],
                        "depth_mm": size[1],
                        "height_mm": size[2],
                        "origin_mm": origin,
                    },
                    {
                        "id": f"cut_{index}",
                        "type": "boolean",
                        "schema_version": 1,
                        "op": "cut",
                        "target": "house",
                        "tool": cutter,
                    },
                ]
            )
        if self.roof == "flat":
            operations.extend(
                [
                    {
                        "id": "roof",
                        "type": "create_box",
                        "schema_version": 1,
                        "width_mm": self.length_mm + self.overhang_mm * 2,
                        "depth_mm": self.width_mm + self.overhang_mm * 2,
                        "height_mm": self.roof_height_mm,
                        "origin_mm": (-self.overhang_mm, -self.overhang_mm, height),
                    },
                    {
                        "id": "join_roof",
                        "type": "boolean",
                        "schema_version": 1,
                        "op": "fuse",
                        "target": "house",
                        "tool": "roof",
                    },
                ]
            )
        elif self.roof == "gable":
            operations.extend(
                [
                    {
                        "id": "roof",
                        "type": "extrude",
                        "schema_version": 1,
                        "profile": {
                            "kind": "polygon",
                            "points_mm": [
                                [0, 0],
                                [self.length_mm + self.overhang_mm * 2, 0],
                                [self.length_mm / 2 + self.overhang_mm, -self.roof_height_mm],
                            ],
                        },
                        "height_mm": self.width_mm + self.overhang_mm * 2,
                        "origin_mm": (-self.overhang_mm, -self.overhang_mm, height),
                        "normal": [0, 1, 0],
                        "x_direction": [1, 0, 0],
                    },
                    {
                        "id": "join_roof",
                        "type": "boolean",
                        "schema_version": 1,
                        "op": "fuse",
                        "target": "house",
                        "tool": "roof",
                    },
                ]
            )
        return OperationPlan.model_validate(
            {
                "schema_version": 1,
                "goal": "Editable house facade shell with exact openings and roof",
                "assumptions": [
                    "All dimensions are millimetres.",
                    "The source is a rectangular house-box version.",
                    "Openings are axis-aligned and cut through one exterior wall.",
                ],
                "operations": operations,
                "validation_steps": [
                    "Confirm the wall shell is open only below the roof.",
                    "Confirm each scheduled opening cuts its selected facade.",
                ],
                "expected_outputs": ["house"],
            }
        )
