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

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal[1] = 1

OperationId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$", examples=["box1", "hole_2"])]
EntityRef = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Vec3 = tuple[float, float, float]
Axis = Literal["x", "y", "z"]

Positive = Annotated[float, Field(gt=0, le=10_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


Profile = Annotated[RectangleProfile | CircleProfile | PolygonProfile, Field(discriminator="kind")]


# --- operations ------------------------------------------------------------------------------


class OperationBase(Strict):
    id: OperationId
    schema_version: Literal[1] = SCHEMA_VERSION


class CreateBox(OperationBase):
    """Axis-aligned box. Its minimum corner sits at `origin_mm` unless `centered`."""

    type: Literal["create_box"]
    width_mm: Positive
    depth_mm: Positive
    height_mm: Positive
    origin_mm: Vec3 = (0.0, 0.0, 0.0)
    centered: bool = False


class CreateCylinder(OperationBase):
    """Cylinder along `axis`; base centre at `origin_mm`."""

    type: Literal["create_cylinder"]
    diameter_mm: Positive
    height_mm: Positive
    axis: Axis = "z"
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


class Extrude(OperationBase):
    """Extrude a 2D profile drawn on the XY plane at `origin_mm` along +Z by `height_mm`."""

    type: Literal["extrude"]
    profile: Profile
    height_mm: Positive
    origin_mm: Vec3 = (0.0, 0.0, 0.0)


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
    | Extrude
    | Boolean
    | Fillet
    | Chamfer
    | AddHole
    | Translate
    | Rotate
    | SetDimensions
    | SetParameter,
    Field(discriminator="type"),
]

OPERATION_TYPES: tuple[str, ...] = (
    "create_box",
    "create_cylinder",
    "extrude",
    "boolean",
    "fillet",
    "chamfer",
    "add_hole",
    "translate",
    "rotate",
    "set_dimensions",
    "set_parameter",
)

# Operations that create a new body named after their id.
CREATORS = frozenset({"create_box", "create_cylinder", "extrude"})


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
