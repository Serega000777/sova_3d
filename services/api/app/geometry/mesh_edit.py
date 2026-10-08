"""Lightweight API contract for direct mesh-edit requests.

Keep these request models aligned with ``worker.meshedit``.  The API container deliberately
does not ship compute dependencies, so importing the worker implementation at request-routing
time would make the orchestration-only image fail before it can serve traffic.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Vec3 = tuple[float, float, float]

MAX_SELECTION_POINTS = 30_000
MAX_OPERATIONS = 32


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Selection(Strict):
    """Picked components as millimetre coordinates: 1 point per vertex, 2 per edge, 3 per face."""

    kind: Literal["vertex", "edge", "face"]
    points_mm: list[Vec3] = Field(min_length=1, max_length=MAX_SELECTION_POINTS)

    @model_validator(mode="after")
    def _arity(self) -> Selection:
        per = {"vertex": 1, "edge": 2, "face": 3}[self.kind]
        if len(self.points_mm) % per:
            raise ValueError(f"a {self.kind} selection needs {per} points per component")
        return self


class FaceSelection(Selection):
    kind: Literal["face"] = "face"


class EdgeSelection(Selection):
    kind: Literal["edge"] = "edge"


class MoveOp(Strict):
    op: Literal["move"] = "move"
    selection: Selection
    delta_mm: Vec3 | None = None
    along_normal_mm: float | None = None

    @model_validator(mode="after")
    def _one_way(self) -> MoveOp:
        if (self.delta_mm is None) == (self.along_normal_mm is None):
            raise ValueError("give exactly one of delta_mm and along_normal_mm")
        return self


class ExtrudeOp(Strict):
    op: Literal["extrude"] = "extrude"
    selection: FaceSelection
    distance_mm: float


class InsetOp(Strict):
    op: Literal["inset"] = "inset"
    selection: FaceSelection
    amount_mm: Annotated[float, Field(gt=0)]


class DeleteFacesOp(Strict):
    op: Literal["delete_faces"] = "delete_faces"
    selection: FaceSelection
    fill: bool = True


class BevelEdgesOp(Strict):
    """`width_mm` is how far the bevel reaches along each adjoining face. One segment is a
    straight chamfer; more segments round it into a fillet of that reach."""

    op: Literal["bevel_edges"] = "bevel_edges"
    selection: EdgeSelection
    width_mm: Annotated[float, Field(gt=0)]
    segments: Annotated[int, Field(ge=1, le=16)] = 1


class Circle(Strict):
    shape: Literal["circle"] = "circle"
    diameter_mm: Annotated[float, Field(gt=0)]


class Square(Strict):
    shape: Literal["square"] = "square"
    width_mm: Annotated[float, Field(gt=0)]
    height_mm: Annotated[float, Field(gt=0)] | None = None
    rotation_deg: float = 0.0


class Area(Strict):
    width_mm: Annotated[float, Field(gt=0)]
    length_mm: Annotated[float, Field(gt=0)]
    rotation_deg: float = 0.0


class Ribs(Strict):
    """Parallel bars (raised) or grooves (recessed) running along the area's length."""

    shape: Literal["ribs"] = "ribs"
    area: Area
    pitch_mm: Annotated[float, Field(gt=0)]
    rib_width_mm: Annotated[float, Field(gt=0)]
    angle_deg: float = 0.0


class Knurl(Strict):
    """V-grooves cut into the surface: one set (straight) or two crossing sets (diamond)."""

    shape: Literal["knurl"] = "knurl"
    area: Area
    pattern: Literal["straight", "diamond"] = "diamond"
    pitch_mm: Annotated[float, Field(gt=0)]
    angle_deg: float = 45.0


Profile = Annotated[Circle | Square | Ribs | Knurl, Field(discriminator="shape")]


class DetailOp(Strict):
    """A dimensioned feature on a flat patch of the surface, raised from it or cut into it."""

    op: Literal["detail"] = "detail"
    at_mm: Vec3
    normal_hint: Vec3 | None = None
    profile: Profile
    mode: Literal["raised", "recessed"] = "raised"
    depth_mm: Annotated[float, Field(gt=0)]


Operation = Annotated[
    MoveOp | ExtrudeOp | InsetOp | DeleteFacesOp | BevelEdgesOp | DetailOp,
    Field(discriminator="op"),
]


class EditRequest(Strict):
    operations: list[Operation] = Field(min_length=1, max_length=MAX_OPERATIONS)
    preview: bool = False
    expected_faces: int | None = None
    tolerance_mm: Annotated[float, Field(gt=0)] = 0.2
