"""Outlined region (T-101, F-062): the part of the model the user pointed at.

A user circles an area on screen and says what they want there. The client turns that
outline into something the kernel and the planner can both reason about — a volume in
canonical millimetres, plus the surface it was drawn on — and the validator holds the plan
to it (T-103). Screen coordinates never leave the client: by the time a region reaches the
API it is geometry, not pixels.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Axis = Literal["x", "y", "z"]
Millimetres = Annotated[float, Field(ge=-100_000, le=100_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoxRegion(Strict):
    """An axis-aligned volume in world millimetres — what a rectangular drag becomes."""

    kind: Literal["box"] = "box"
    min_mm: tuple[Millimetres, Millimetres, Millimetres]
    max_mm: tuple[Millimetres, Millimetres, Millimetres]

    @model_validator(mode="after")
    def _ordered(self) -> BoxRegion:
        if any(hi <= lo for lo, hi in zip(self.min_mm, self.max_mm, strict=True)):
            raise ValueError("region max_mm must be greater than min_mm on every axis")
        return self

    @property
    def size_mm(self) -> tuple[float, float, float]:
        return tuple(hi - lo for lo, hi in zip(self.min_mm, self.max_mm, strict=True))  # type: ignore[return-value]

    @property
    def centre_mm(self) -> tuple[float, float, float]:
        return tuple((lo + hi) / 2 for lo, hi in zip(self.min_mm, self.max_mm, strict=True))  # type: ignore[return-value]

    def contains(self, point: tuple[float, float, float], tolerance: float = 0.001) -> bool:
        return all(
            lo - tolerance <= value <= hi + tolerance
            for lo, hi, value in zip(self.min_mm, self.max_mm, point, strict=True)
        )


class LassoRegion(Strict):
    """A freehand outline, projected onto one plane of the model.

    The polygon is 2-D in the plane's own axes (the two that are not `axis`), at the
    plane's offset along `axis`, extruded through `depth_mm`. That is exactly what a finger
    or a pencil draws on a face, and it is enough for the kernel to work with.
    """

    kind: Literal["lasso"] = "lasso"
    axis: Axis  # the normal of the surface the outline was drawn on
    offset_mm: Millimetres  # where that surface sits along `axis`
    # How far through the material the outline reaches. Clients send the body's extent along
    # `axis`, so anything cut or raised under the outline is inside the region by construction.
    depth_mm: Annotated[float, Field(gt=0, le=10_000)] = 10.0
    points_mm: list[tuple[Millimetres, Millimetres]] = Field(min_length=3, max_length=256)

    @model_validator(mode="after")
    def _has_area(self) -> LassoRegion:
        xs = [p[0] for p in self.points_mm]
        ys = [p[1] for p in self.points_mm]
        if max(xs) - min(xs) <= 0 or max(ys) - min(ys) <= 0:
            raise ValueError("the outline has no area")
        return self

    def bounds(self) -> BoxRegion:
        """The volume the outline sweeps — what scope checks are measured against."""
        xs = [p[0] for p in self.points_mm]
        ys = [p[1] for p in self.points_mm]
        plane_min, plane_max = (min(xs), min(ys)), (max(xs), max(ys))
        half = self.depth_mm / 2
        low, high = self.offset_mm - half, self.offset_mm + half
        if self.axis == "x":
            return BoxRegion(
                min_mm=(low, plane_min[0], plane_min[1]),
                max_mm=(high, plane_max[0], plane_max[1]),
            )
        if self.axis == "y":
            return BoxRegion(
                min_mm=(plane_min[0], low, plane_min[1]),
                max_mm=(plane_max[0], high, plane_max[1]),
            )
        return BoxRegion(
            min_mm=(plane_min[0], plane_min[1], low),
            max_mm=(plane_max[0], plane_max[1], high),
        )


Region = Annotated[BoxRegion | LassoRegion, Field(discriminator="kind")]


class RegionSelection(Strict):
    """What the client sends with a prompt: where, and on what."""

    region: Region
    # The body the outline was drawn on, when the client knows it (T-049 entity id).
    target: str | None = Field(default=None, max_length=64)
    # Outward normal of the surface under the outline, for "raise this" / "cut here".
    surface_axis: Axis | None = None
    surface_sign: Literal["+", "-"] | None = None

    def bounds(self) -> BoxRegion:
        return self.region if isinstance(self.region, BoxRegion) else self.region.bounds()

    @property
    def surface_mm(self) -> float | None:
        """Where the surface under the outline sits along `surface_axis`, in mm.

        A lasso carries it exactly; a box falls back to the face the outline faces. Without
        a surface axis there is nothing to measure against, and callers say so.
        """
        if self.surface_axis is None:
            return None
        if isinstance(self.region, LassoRegion) and self.region.axis == self.surface_axis:
            return self.region.offset_mm
        box = self.bounds()
        index = "xyz".index(self.surface_axis)
        return box.max_mm[index] if self.surface_sign != "-" else box.min_mm[index]

    def describe(self) -> str:
        """One line for the planner prompt, in the units the plan is written in."""
        box = self.bounds()
        size = box.size_mm
        centre = box.centre_mm
        face = (
            f" on the {self.surface_sign}{self.surface_axis} face"
            if self.surface_axis and self.surface_sign
            else ""
        )
        return (
            f"The user outlined a region{face}"
            + (f" of body '{self.target}'" if self.target else "")
            + f": {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm"
            f" centred at ({centre[0]:.1f}, {centre[1]:.1f}, {centre[2]:.1f}) mm,"
            f" spanning x {box.min_mm[0]:.1f}..{box.max_mm[0]:.1f},"
            f" y {box.min_mm[1]:.1f}..{box.max_mm[1]:.1f},"
            f" z {box.min_mm[2]:.1f}..{box.max_mm[2]:.1f}."
            " Put the change inside it; anything outside will be rejected."
        )


def parse_region(payload: Any) -> RegionSelection:
    return RegionSelection.model_validate(payload)
