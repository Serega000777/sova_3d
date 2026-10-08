"""Operation schema v1 (T-032): the only vocabulary a planner may emit.

Rules baked into the types:
- every length is millimetres (field names end in `_mm`), angles in degrees;
- an operation is addressed by its `id`; the body it produces is the entity
  with the same name, so later operations reference it by id;
- edges/faces are selected by deterministic geometric selectors, never by
  kernel-internal indices, so a plan replays identically (T-040);
- unknown operation types or extra parameters are rejected at parse time.

`python -m app.geometry.operations --emit-schema` refreshes
packages/contracts/operation-plan.schema.json.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal[1] = 1

OperationId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$", examples=["box1", "hole_2"])]
EntityRef = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Vec3 = tuple[float, float, float]
Axis = Literal["x", "y", "z"]

Positive = Annotated[float, Field(gt=0, le=10_000)]
BoxDimension = Annotated[float, Field(gt=0, le=50_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _validate_profile_frame(normal: Vec3, x_direction: Vec3) -> None:
    normal_length = math.sqrt(sum(component * component for component in normal))
    x_length = math.sqrt(sum(component * component for component in x_direction))
    if normal_length <= 1e-9 or x_length <= 1e-9:
        raise ValueError("profile plane directions must be nonzero")
    cosine = sum(a * b for a, b in zip(normal, x_direction, strict=True)) / (
        normal_length * x_length
    )
    if abs(cosine) > 1e-6:
        raise ValueError("profile plane normal and x_direction must be perpendicular")


def _unit(vector: Vec3) -> Vec3:
    length = math.sqrt(sum(component * component for component in vector))
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _same_direction(left: Vec3, right: Vec3) -> bool:
    return sum(a * b for a, b in zip(_unit(left), _unit(right), strict=True)) >= 1 - 1e-9


def _validate_clamped_nurbs_basis(
    label: str,
    pole_count: int,
    degree: int,
    knots: list[float],
    multiplicities: list[int],
) -> None:
    if degree >= pole_count:
        raise ValueError(f"{label} degree must be smaller than its pole count")
    if len(knots) != len(multiplicities):
        raise ValueError(f"{label} knots and multiplicities must have the same length")
    if any(left >= right for left, right in zip(knots, knots[1:], strict=False)):
        raise ValueError(f"{label} knots must be strictly increasing")
    if multiplicities[0] != degree + 1 or multiplicities[-1] != degree + 1:
        raise ValueError(f"{label} endpoint multiplicities must equal degree + 1")
    if any(value > degree for value in multiplicities[1:-1]):
        raise ValueError(f"{label} interior multiplicities must not exceed its degree")
    if sum(multiplicities) != pole_count + degree + 1:
        raise ValueError(f"{label} multiplicities do not match its poles and degree")


# --- selectors -------------------------------------------------------------------------------


class AllEdges(Strict):
    kind: Literal["all_edges"] = "all_edges"


class EdgesParallelTo(Strict):
    kind: Literal["edges_parallel_to"] = "edges_parallel_to"
    axis: Axis
    # Only the edges on the body's bounding box: the outer corners, never those inside
    # pockets or holes — what "rounded corners" means for a part with compartments.
    outer: bool = False


class EdgesOfFace(Strict):
    kind: Literal["edges_of_face"] = "edges_of_face"
    face: FaceSelector


class FaceByNormal(Strict):
    """The planar face whose outward normal points along ±axis (e.g. the top face: +z)."""

    kind: Literal["face_by_normal"] = "face_by_normal"
    axis: Axis
    sign: Literal["+", "-"] = "+"


class AllFaces(Strict):
    kind: Literal["all_faces"] = "all_faces"


FaceSelector = Annotated[FaceByNormal | AllFaces, Field(discriminator="kind")]
EdgeSelector = Annotated[AllEdges | EdgesParallelTo | EdgesOfFace, Field(discriminator="kind")]


# --- profiles (for extrude) -----------------------------------------------------------------


class RectangleProfile(Strict):
    kind: Literal["rectangle"] = "rectangle"
    width_mm: Positive
    depth_mm: Positive


class CircleProfile(Strict):
    kind: Literal["circle"] = "circle"
    diameter_mm: Positive


class PolygonProfile(Strict):
    kind: Literal["polygon"] = "polygon"
    points_mm: list[tuple[float, float]] = Field(min_length=3, max_length=256)


SketchPoint = Annotated[int, Field(ge=0, le=127)]


class FixedConstraint(Strict):
    """Keep one sketch point at the coordinates supplied in ``points_mm``."""

    kind: Literal["fixed"] = "fixed"
    point: SketchPoint


class HorizontalConstraint(Strict):
    kind: Literal["horizontal"] = "horizontal"
    start: SketchPoint
    end: SketchPoint


class VerticalConstraint(Strict):
    kind: Literal["vertical"] = "vertical"
    start: SketchPoint
    end: SketchPoint


class CoincidentConstraint(Strict):
    kind: Literal["coincident"] = "coincident"
    first: SketchPoint
    second: SketchPoint


class DistanceConstraint(Strict):
    kind: Literal["distance"] = "distance"
    start: SketchPoint
    end: SketchPoint
    distance_mm: Positive


class EqualLengthConstraint(Strict):
    kind: Literal["equal_length"] = "equal_length"
    first_start: SketchPoint
    first_end: SketchPoint
    second_start: SketchPoint
    second_end: SketchPoint


class ParallelConstraint(Strict):
    kind: Literal["parallel"] = "parallel"
    first_start: SketchPoint
    first_end: SketchPoint
    second_start: SketchPoint
    second_end: SketchPoint


class PerpendicularConstraint(Strict):
    kind: Literal["perpendicular"] = "perpendicular"
    first_start: SketchPoint
    first_end: SketchPoint
    second_start: SketchPoint
    second_end: SketchPoint


SketchConstraint = Annotated[
    FixedConstraint
    | HorizontalConstraint
    | VerticalConstraint
    | CoincidentConstraint
    | DistanceConstraint
    | EqualLengthConstraint
    | ParallelConstraint
    | PerpendicularConstraint,
    Field(discriminator="kind"),
]


class LineSketchSegment(Strict):
    """A straight segment from point i to point i+1 (wrapping at the end)."""

    kind: Literal["line"] = "line"


class ArcSketchSegment(Strict):
    """A circular arc from point i to point i+1 around ``center_mm``."""

    kind: Literal["arc"] = "arc"
    center_mm: tuple[float, float]
    clockwise: bool = False


class SplineSketchSegment(Strict):
    """An interpolating B-spline through the endpoints and these interior points."""

    kind: Literal["spline"] = "spline"
    through_points_mm: list[tuple[float, float]] = Field(min_length=1, max_length=30)


class NurbsSketchSegment(Strict):
    """A clamped rational B-spline whose first/last poles are the segment endpoints."""

    kind: Literal["nurbs"] = "nurbs"
    control_points_mm: list[tuple[float, float]] = Field(min_length=1, max_length=30)
    degree: Annotated[int, Field(ge=1, le=5)]
    weights: list[Annotated[float, Field(gt=0, le=1_000_000)]] = Field(min_length=3, max_length=32)
    knots: list[Annotated[float, Field(ge=-1_000_000, le=1_000_000)]] = Field(
        min_length=2, max_length=32
    )
    multiplicities: list[Annotated[int, Field(ge=1, le=6)]] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def valid_nurbs_basis(self) -> NurbsSketchSegment:
        pole_count = len(self.control_points_mm) + 2
        if len(self.weights) != pole_count:
            raise ValueError("NURBS weights must match its pole count")
        _validate_clamped_nurbs_basis(
            "NURBS", pole_count, self.degree, self.knots, self.multiplicities
        )
        return self


SketchSegment = Annotated[
    LineSketchSegment | ArcSketchSegment | SplineSketchSegment | NurbsSketchSegment,
    Field(discriminator="kind"),
]


class SketchProfile(Strict):
    """A closed sketch solved before it becomes an exact B-Rep wire.

    Point indices are stable plan data rather than kernel topology ids. The numerical solver
    moves the supplied starting points only as far as needed and refuses inconsistent systems.
    When ``segments`` is omitted every point is joined to the next with a line for backward
    compatibility. Otherwise segment i joins point i to point i+1, wrapping at the end.
    """

    kind: Literal["sketch"] = "sketch"
    points_mm: list[tuple[float, float]] = Field(min_length=2, max_length=128)
    segments: list[SketchSegment] | None = Field(default=None, min_length=2, max_length=128)
    constraints: list[SketchConstraint] = Field(default_factory=list, max_length=256)
    tolerance_mm: Annotated[float, Field(gt=0, le=0.1)] = 1e-5

    @model_validator(mode="after")
    def constraints_reference_points(self) -> SketchProfile:
        limit = len(self.points_mm)
        if self.segments is None:
            if limit < 3:
                raise ValueError("an implicit line sketch needs at least three points")
        elif len(self.segments) != limit:
            raise ValueError("sketch segments must match the number of boundary points")
        segments = self.segments or [LineSketchSegment() for _ in self.points_mm]
        for index, segment in enumerate(segments):
            start = self.points_mm[index]
            end = self.points_mm[(index + 1) % limit]
            if math.hypot(start[0] - end[0], start[1] - end[1]) <= self.tolerance_mm:
                raise ValueError("sketch segment endpoints must be distinct")
            if isinstance(segment, SplineSketchSegment):
                chain = [start, *segment.through_points_mm, end]
                if any(
                    math.hypot(left[0] - right[0], left[1] - right[1]) <= self.tolerance_mm
                    for left, right in zip(chain, chain[1:], strict=False)
                ):
                    raise ValueError("spline interpolation points must be distinct")
                continue
            if isinstance(segment, NurbsSketchSegment):
                chain = [start, *segment.control_points_mm, end]
                if any(
                    math.hypot(left[0] - right[0], left[1] - right[1]) <= self.tolerance_mm
                    for left, right in zip(chain, chain[1:], strict=False)
                ):
                    raise ValueError("NURBS control points must be consecutively distinct")
                continue
            if not isinstance(segment, ArcSketchSegment):
                continue
            start_radius = math.hypot(
                start[0] - segment.center_mm[0], start[1] - segment.center_mm[1]
            )
            end_radius = math.hypot(end[0] - segment.center_mm[0], end[1] - segment.center_mm[1])
            if min(start_radius, end_radius) <= self.tolerance_mm:
                raise ValueError("arc endpoints must differ from its center")
            if abs(start_radius - end_radius) > self.tolerance_mm:
                raise ValueError("arc endpoints must have the same radius")
        for constraint in self.constraints:
            indices = [
                value
                for name, value in constraint.model_dump().items()
                if name
                in {
                    "point",
                    "start",
                    "end",
                    "first",
                    "second",
                    "first_start",
                    "first_end",
                    "second_start",
                    "second_end",
                }
            ]
            if any(index >= limit for index in indices):
                raise ValueError(f"{constraint.kind} constraint references a missing point")
            if isinstance(
                constraint, (HorizontalConstraint, VerticalConstraint, DistanceConstraint)
            ):
                if constraint.start == constraint.end:
                    raise ValueError(f"{constraint.kind} constraint needs two different points")
            if (
                isinstance(constraint, CoincidentConstraint)
                and constraint.first == constraint.second
            ):
                raise ValueError("coincident constraint needs two different points")
            if isinstance(
                constraint,
                (EqualLengthConstraint, ParallelConstraint, PerpendicularConstraint),
            ) and (
                constraint.first_start == constraint.first_end
                or constraint.second_start == constraint.second_end
            ):
                raise ValueError(f"{constraint.kind} constraint needs two nonzero segments")
        return self


Profile = Annotated[
    RectangleProfile | CircleProfile | PolygonProfile | SketchProfile,
    Field(discriminator="kind"),
]


class ProfileSection(Strict):
    profile: Profile
    origin_mm: Vec3 = (0.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    x_direction: Vec3 = (1.0, 0.0, 0.0)

    @model_validator(mode="after")
    def valid_frame(self) -> ProfileSection:
        _validate_profile_frame(self.normal, self.x_direction)
        return self


# --- operations ------------------------------------------------------------------------------


class OperationBase(Strict):
    id: OperationId
    schema_version: Literal[1] = SCHEMA_VERSION


class CreateBox(OperationBase):
    """Axis-aligned box. Its minimum corner sits at `origin_mm` unless `centered`."""

    type: Literal["create_box"]
    # Buildings use the same exact CAD primitive as smaller parts, but can span up to 50 m.
    width_mm: BoxDimension
    depth_mm: BoxDimension
    height_mm: BoxDimension
    origin_mm: Vec3 = (0.0, 0.0, 0.0)
    centered: bool = False


class CreateCylinder(OperationBase):
    """Cylinder along `axis`; base centre at `origin_mm`."""

    type: Literal["create_cylinder"]
    diameter_mm: Positive
    height_mm: Positive
    axis: Axis = "z"
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class CreateSphere(OperationBase):
    """Sphere centred at `origin_mm`."""

    type: Literal["create_sphere"]
    diameter_mm: Positive
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class CreateCone(OperationBase):
    """Cone or frustum along `axis`; `origin_mm` is the bottom-face centre."""

    type: Literal["create_cone"]
    bottom_diameter_mm: Positive
    top_diameter_mm: Annotated[float, Field(ge=0, le=10_000)] = 0.0
    height_mm: Positive
    axis: Axis = "z"
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class CreateTorus(OperationBase):
    """Ring centred at `origin_mm`, with `axis` through its hole."""

    type: Literal["create_torus"]
    outer_diameter_mm: Positive
    tube_diameter_mm: Positive
    axis: Axis = "z"
    origin_mm: Vec3 = (0.0, 0.0, 0.0)

    @model_validator(mode="after")
    def tube_fits_ring(self) -> CreateTorus:
        if self.tube_diameter_mm * 2 >= self.outer_diameter_mm:
            raise ValueError("tube diameter must be less than half the outer diameter")
        return self


class Extrude(OperationBase):
    """Extrude a planar profile from ``origin_mm`` along the plane normal."""

    type: Literal["extrude"]
    profile: Profile
    height_mm: Positive
    origin_mm: Vec3 = (0.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    x_direction: Vec3 = (1.0, 0.0, 0.0)

    @model_validator(mode="after")
    def valid_frame(self) -> Extrude:
        _validate_profile_frame(self.normal, self.x_direction)
        return self


class Loft(OperationBase):
    """Create an exact solid through profiles on parallel, consistently oriented planes."""

    type: Literal["loft"]
    sections: list[ProfileSection] = Field(min_length=2, max_length=32)
    ruled: bool = False

    @model_validator(mode="after")
    def sections_do_not_overlap(self) -> Loft:
        first = self.sections[0]
        if any(
            not _same_direction(first.normal, section.normal)
            or not _same_direction(first.x_direction, section.x_direction)
            for section in self.sections[1:]
        ):
            raise ValueError("loft sections must use one parallel profile frame")
        normal = _unit(first.normal)
        offsets = [
            sum(component * axis for component, axis in zip(section.origin_mm, normal, strict=True))
            for section in self.sections
        ]
        if any(
            abs(left - right) <= 1e-9
            for index, left in enumerate(offsets)
            for right in offsets[index + 1 :]
        ):
            raise ValueError("loft sections must lie on different parallel planes")
        return self


class Sweep(OperationBase):
    """Sweep a closed profile along an open 3D polyline using the corrected Frenet frame."""

    type: Literal["sweep"]
    profile: Profile
    path_mm: list[Vec3] = Field(min_length=2, max_length=256)

    @model_validator(mode="after")
    def path_has_no_zero_segments(self) -> Sweep:
        if any(a == b for a, b in zip(self.path_mm, self.path_mm[1:], strict=False)):
            raise ValueError("sweep path has a zero-length segment")
        return self


class Revolve(OperationBase):
    """Revolve a closed profile in the radial/axial plane around an exact axis."""

    type: Literal["revolve"]
    profile: Profile
    axis: Axis = "z"
    angle_deg: Annotated[float, Field(gt=0, le=360)] = 360.0
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


SurfaceWeight = Annotated[float, Field(gt=0, le=1_000_000)]
SurfaceDegree = Annotated[int, Field(ge=1, le=5)]
SurfaceKnot = Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
SurfaceMultiplicity = Annotated[int, Field(ge=1, le=6)]


class NurbsSurface(OperationBase):
    """Thicken an exact rational tensor-product B-spline patch into a closed B-Rep solid."""

    type: Literal["nurbs_surface"]
    control_points_mm: list[list[Vec3]] = Field(min_length=2, max_length=16)
    weights: list[list[SurfaceWeight]] = Field(min_length=2, max_length=16)
    u_degree: SurfaceDegree
    v_degree: SurfaceDegree
    u_knots: list[SurfaceKnot] = Field(min_length=2, max_length=16)
    v_knots: list[SurfaceKnot] = Field(min_length=2, max_length=16)
    u_multiplicities: list[SurfaceMultiplicity] = Field(min_length=2, max_length=16)
    v_multiplicities: list[SurfaceMultiplicity] = Field(min_length=2, max_length=16)
    thickness_mm: Positive
    tolerance_mm: Annotated[float, Field(gt=0, le=0.1)] = 1e-5

    @model_validator(mode="after")
    def valid_surface(self) -> NurbsSurface:
        u_poles = len(self.control_points_mm)
        v_poles = len(self.control_points_mm[0])
        if (
            v_poles < 2
            or v_poles > 16
            or any(len(row) != v_poles for row in self.control_points_mm)
        ):
            raise ValueError("NURBS surface control points must form a 2..16 by 2..16 grid")
        if len(self.weights) != u_poles or any(len(row) != v_poles for row in self.weights):
            raise ValueError("NURBS surface weights must match its control-point grid")
        _validate_clamped_nurbs_basis(
            "NURBS surface U",
            u_poles,
            self.u_degree,
            self.u_knots,
            self.u_multiplicities,
        )
        _validate_clamped_nurbs_basis(
            "NURBS surface V",
            v_poles,
            self.v_degree,
            self.v_knots,
            self.v_multiplicities,
        )
        origin = self.control_points_mm[0][0]
        vectors = [
            tuple(point[index] - origin[index] for index in range(3))
            for row in self.control_points_mm
            for point in row
        ]
        if not any(
            math.sqrt(
                (left[1] * right[2] - left[2] * right[1]) ** 2
                + (left[2] * right[0] - left[0] * right[2]) ** 2
                + (left[0] * right[1] - left[1] * right[0]) ** 2
            )
            > self.tolerance_mm**2
            for left_index, left in enumerate(vectors)
            for right in vectors[left_index + 1 :]
        ):
            raise ValueError("NURBS surface control net must span a two-dimensional patch")
        return self


class Boolean(OperationBase):
    """Combine two bodies; the result replaces `target` and `tool` is consumed."""

    type: Literal["boolean"]
    op: Literal["cut", "fuse", "common"]
    target: EntityRef
    tool: EntityRef

    @model_validator(mode="after")
    def _distinct(self) -> Boolean:
        if self.target == self.tool:
            raise ValueError("target and tool must be different bodies")
        return self


class Fillet(OperationBase):
    type: Literal["fillet"]
    target: EntityRef
    edges: EdgeSelector
    radius_mm: Positive


class Chamfer(OperationBase):
    type: Literal["chamfer"]
    target: EntityRef
    edges: EdgeSelector
    distance_mm: Positive


class Shell(OperationBase):
    """Hollow the body to a wall of `thickness_mm` (F-007). With `open_face` that face is
    removed so the hollow opens there — a part printed bottom-down needs no support inside;
    without it the void stays enclosed."""

    type: Literal["shell"]
    target: EntityRef
    thickness_mm: Positive
    open_face: FaceSelector | None = None


class AddHole(OperationBase):
    """Cylindrical hole drilled into `face` at `position_mm` (face-local XY), along -normal."""

    type: Literal["add_hole"]
    target: EntityRef
    face: FaceSelector
    position_mm: tuple[float, float]
    diameter_mm: Positive
    depth_mm: Positive | None = Field(default=None, description="omit for a through hole")


class Translate(OperationBase):
    type: Literal["translate"]
    target: EntityRef
    offset_mm: Vec3


class Rotate(OperationBase):
    type: Literal["rotate"]
    target: EntityRef
    axis: Axis
    angle_deg: Annotated[float, Field(gt=-360, lt=360)]
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class LinearPattern(OperationBase):
    """Repeat a body along one axis and fuse the copies into the same result body."""

    type: Literal["linear_pattern"]
    target: EntityRef
    axis: Axis
    count: Annotated[int, Field(ge=2, le=100)]
    spacing_mm: Positive


class CircularPattern(OperationBase):
    """Repeat a body around an axis; count includes the original body."""

    type: Literal["circular_pattern"]
    target: EntityRef
    axis: Axis
    count: Annotated[int, Field(ge=2, le=100)]
    angle_deg: Annotated[float, Field(gt=0, le=360)] = 360.0
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class Mirror(OperationBase):
    """Mirror a body across an axis-aligned plane, optionally keeping the original."""

    type: Literal["mirror"]
    target: EntityRef
    axis: Axis
    offset_mm: Annotated[float, Field(ge=-10_000, le=10_000)] = 0.0
    keep_original: bool = True


class SetDimensions(OperationBase):
    """Uniformly rescale a body so its bounding box matches the given sizes (any subset)."""

    type: Literal["set_dimensions"]
    target: EntityRef
    width_mm: Positive | None = None
    depth_mm: Positive | None = None
    height_mm: Positive | None = None

    @model_validator(mode="after")
    def _any_dimension(self) -> SetDimensions:
        if self.width_mm is None and self.depth_mm is None and self.height_mm is None:
            raise ValueError("at least one dimension is required")
        return self


class SetParameter(OperationBase):
    """T-038: edit one numeric parameter of an earlier operation; the plan is replayed."""

    type: Literal["set_parameter"]
    operation: OperationId
    parameter: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*_(mm|deg)$")]
    value: Annotated[float, Field(gt=-10_000, le=10_000)]


Operation = Annotated[
    CreateBox
    | CreateCylinder
    | CreateSphere
    | CreateCone
    | CreateTorus
    | Extrude
    | Loft
    | Sweep
    | Revolve
    | NurbsSurface
    | Boolean
    | Fillet
    | Chamfer
    | AddHole
    | Shell
    | Translate
    | Rotate
    | LinearPattern
    | CircularPattern
    | Mirror
    | SetDimensions
    | SetParameter,
    Field(discriminator="type"),
]

OPERATION_TYPES: tuple[str, ...] = (
    "create_box",
    "create_cylinder",
    "create_sphere",
    "create_cone",
    "create_torus",
    "extrude",
    "loft",
    "sweep",
    "revolve",
    "nurbs_surface",
    "boolean",
    "fillet",
    "chamfer",
    "add_hole",
    "shell",
    "translate",
    "rotate",
    "linear_pattern",
    "circular_pattern",
    "mirror",
    "set_dimensions",
    "set_parameter",
)

# Operations that create a new body named after their id.
CREATORS = frozenset(
    {
        "create_box",
        "create_cylinder",
        "create_sphere",
        "create_cone",
        "create_torus",
        "extrude",
        "loft",
        "sweep",
        "revolve",
        "nurbs_surface",
    }
)


class OperationPlan(Strict):
    """What a planner returns. Geometry execution never starts while
    `required_clarifications` is non-empty."""

    schema_version: Literal[1] = SCHEMA_VERSION
    goal: Annotated[str, Field(min_length=1, max_length=2000)]
    assumptions: list[str] = Field(default_factory=list)
    required_clarifications: list[str] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list, max_length=256)
    validation_steps: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_resolve(self) -> OperationPlan:
        """Ids are unique; every entity/operation reference points at an earlier operation."""
        seen: set[str] = set()
        bodies: set[str] = set()
        for op in self.operations:
            if op.id in seen:
                raise ValueError(f"duplicate operation id {op.id!r}")
            for ref in _body_refs(op):
                if ref not in bodies:
                    raise ValueError(f"operation {op.id!r} references unknown body {ref!r}")
            if isinstance(op, SetParameter) and op.operation not in seen:
                raise ValueError(f"operation {op.id!r} edits unknown operation {op.operation!r}")
            seen.add(op.id)
            if op.type in CREATORS:
                bodies.add(op.id)
            if isinstance(op, Boolean):
                bodies.discard(op.tool)
        return self

    @property
    def needs_clarification(self) -> bool:
        return bool(self.required_clarifications)


def _body_refs(op: Operation) -> list[str]:
    refs: list[str] = []
    target = getattr(op, "target", None)
    if isinstance(target, str):
        refs.append(target)
    if isinstance(op, Boolean):
        refs.append(op.tool)
    return refs


_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def parse_plan(payload: object) -> OperationPlan:
    """Strict parse of an untrusted planner payload."""
    return OperationPlan.model_validate(payload)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    if "--emit-schema" in sys.argv:
        target = Path(__file__).resolve().parents[4] / "packages" / "contracts"
        schema = OperationPlan.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (target / "operation-plan.schema.json").write_text(
            json.dumps(schema, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"wrote {target / 'operation-plan.schema.json'}")
