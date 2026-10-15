"""Exact rectangular-house facade editor built from existing kernel operations."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass
from pydantic_core import ArgsKwargs

from app.geometry.operations import OperationPlan

FacadeSide = Literal["front", "back", "left", "right"]
OpeningKind = Literal["window", "door", "opening"]
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
    opening_id: Annotated[str | None, Field(pattern=r"^[a-z0-9_-]{1,64}$")] = None
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
class SurfaceMaterial:
    surface_key: Annotated[str, Field(pattern=r"^[a-z0-9_.-]{1,160}$")]
    colour: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
    material_id: Annotated[str | None, Field(pattern=r"^[a-z0-9_-]{1,64}$")] = None
    unit_price_per_m2: Annotated[float | None, Field(ge=0, le=1_000_000)] = None
    currency: Annotated[str | None, Field(pattern=r"^[A-Z]{3}$")] = None
    price_source_url: Annotated[
        str | None,
        Field(max_length=500, pattern=r"^https://[^\s]+$"),
    ] = None

    @model_validator(mode="after")
    def pricing_is_complete(self) -> SurfaceMaterial:
        values = (self.unit_price_per_m2, self.currency, self.price_source_url)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError(
                "facade price requires unit_price_per_m2, currency and price_source_url together"
            )
        return self


def opening_key(opening: FacadeOpening, _index: int = 0) -> str:
    """Return an explicit identity or a safe geometry-derived legacy identity.

    The fallback deliberately excludes list position: removing or reordering another opening
    must never retarget a material assignment to this opening.  A legacy opening that moves or
    changes size gets a new identity, so its old frame assignment is dropped rather than guessed.
    """
    if opening.opening_id is not None:
        return opening.opening_id
    identity = "|".join(
        (
            opening.kind,
            opening.side,
            float(opening.center_mm).hex(),
            float(opening.width_mm).hex(),
            float(opening.height_mm).hex(),
            float(opening.sill_mm).hex(),
        )
    )
    return f"legacy-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


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
    surface_assignments: list[SurfaceMaterial] = Field(default_factory=list, max_length=512)

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
        identities = [opening_key(opening, index) for index, opening in enumerate(self.openings)]
        if len(set(identities)) != len(identities):
            raise ValueError("each facade opening_id must be unique")
        keys = surface_keys(self)
        assigned = [assignment.surface_key for assignment in self.surface_assignments]
        if len(set(assigned)) != len(assigned):
            raise ValueError("each facade surface key may be assigned at most once")
        unknown = sorted(set(assigned) - keys)
        if unknown:
            raise ValueError(f"unknown facade surface keys: {', '.join(unknown)}")
        currencies = {
            assignment.currency
            for assignment in self.surface_assignments
            if assignment.currency is not None
        }
        if len(currencies) > 1:
            raise ValueError("one facade variant may use only one estimate currency")
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
            semantic = opening_key(opening, index - 1)
            operation_token = hashlib.sha256(semantic.encode()).hexdigest()[:16]
            cutter = f"opening_{operation_token}"
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
                        "id": f"cut_{operation_token}",
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


def surface_records(request: FacadeRequest) -> list[dict[str, str]]:
    """Stable semantic keys exposed to clients; no OCCT or tessellation index escapes."""
    records = [
        {"key": f"wall.{side}", "kind": "wall", "side": side}
        for side in ("front", "back", "left", "right")
    ]
    if request.roof == "flat":
        records.append({"key": "roof.top", "kind": "roof", "side": "top"})
    elif request.roof == "gable":
        records.extend(
            [
                {"key": "roof.slope.left", "kind": "roof", "side": "left"},
                {"key": "roof.slope.right", "kind": "roof", "side": "right"},
            ]
        )
    for index, opening in enumerate(request.openings):
        identity = opening_key(opening, index)
        roles = (
            ("left", "right", "head", "sill")
            if opening.kind != "door"
            else ("left", "right", "head")
        )
        records.extend(
            {
                "key": f"opening.{identity}.{role}",
                "kind": "opening_frame",
                "side": opening.side,
                "opening_id": identity,
                "frame_role": role,
            }
            for role in roles
        )
    return records


def surface_keys(request: FacadeRequest) -> set[str]:
    return {record["key"] for record in surface_records(request)}


def surface_areas_m2(request: FacadeRequest) -> dict[str, float]:
    """Analytic finish area for every stable semantic facade surface.

    These are procurement areas, not triangulation-derived guesses: wall faces use the exact
    house dimensions minus openings, roof faces use the exact configured roof profile, and
    opening reveals use the validated wall thickness. All inputs are millimetres; output is m².
    """
    height = request.floor_height_mm * request.floors
    areas_mm2: dict[str, float] = {
        "wall.front": request.length_mm * height,
        "wall.back": request.length_mm * height,
        "wall.left": request.width_mm * height,
        "wall.right": request.width_mm * height,
    }
    for index, opening in enumerate(request.openings):
        areas_mm2[f"wall.{opening.side}"] -= opening.width_mm * opening.height_mm
        identity = opening_key(opening, index)
        areas_mm2[f"opening.{identity}.left"] = opening.height_mm * request.wall_thickness_mm
        areas_mm2[f"opening.{identity}.right"] = opening.height_mm * request.wall_thickness_mm
        areas_mm2[f"opening.{identity}.head"] = opening.width_mm * request.wall_thickness_mm
        if opening.kind != "door":
            areas_mm2[f"opening.{identity}.sill"] = opening.width_mm * request.wall_thickness_mm
    roof_length = request.length_mm + request.overhang_mm * 2
    roof_width = request.width_mm + request.overhang_mm * 2
    if request.roof == "flat":
        areas_mm2["roof.top"] = roof_length * roof_width
    elif request.roof == "gable":
        slope_width = ((roof_width / 2) ** 2 + request.roof_height_mm**2) ** 0.5
        areas_mm2["roof.slope.left"] = roof_length * slope_width
        areas_mm2["roof.slope.right"] = roof_length * slope_width
    return {key: area / 1_000_000 for key, area in areas_mm2.items()}


def variant_estimate(request: FacadeRequest) -> dict[str, Any]:
    """Return category quantities and a source-backed estimate for assigned finishes only."""
    areas = surface_areas_m2(request)
    category_areas = {
        "walls": sum(area for key, area in areas.items() if key.startswith("wall.")),
        "roof": sum(area for key, area in areas.items() if key.startswith("roof.")),
        "opening_frames": sum(area for key, area in areas.items() if key.startswith("opening.")),
    }
    assigned_area = 0.0
    priced_area = 0.0
    estimated_cost = 0.0
    currency: str | None = None
    for assignment in request.surface_assignments:
        area = areas[assignment.surface_key]
        assigned_area += area
        if assignment.unit_price_per_m2 is None:
            continue
        priced_area += area
        estimated_cost += area * assignment.unit_price_per_m2
        currency = assignment.currency
    return {
        "surface_areas_m2": areas,
        "category_areas_m2": category_areas,
        "assigned_area_m2": assigned_area,
        "priced_area_m2": priced_area,
        "unpriced_assigned_area_m2": assigned_area - priced_area,
        "estimated_cost": estimated_cost if priced_area > 0 else None,
        "currency": currency,
    }
