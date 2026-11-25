"""Parametric quick-start shell for a house-design project."""

from __future__ import annotations

import math
from dataclasses import dataclass as plain_dataclass
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Discriminator, Field, Tag
from pydantic.dataclasses import dataclass

from app.geometry.operations import MAX_PLAN_OPERATIONS, OperationPlan

HouseShape = Literal["rectangle", "l_shape", "t_shape"]
HouseLength = Annotated[float, Field(ge=2_000, le=50_000)]
FloorHeight = Annotated[float, Field(ge=2_200, le=6_000)]
FloorCount = Annotated[int, Field(ge=1, le=3)]
UpperFloorSetback = Annotated[float, Field(ge=0, le=10_000)]
StairWidth = Annotated[float, Field(ge=700, le=2_000)]
StairTread = Annotated[float, Field(ge=200, le=400)]
StairSteps = Annotated[int, Field(ge=10, le=30)]
FlightSteps = Annotated[int, Field(ge=3, le=26)]
UTurnFlightSteps = Annotated[int, Field(ge=5, le=14)]
# The winder variant is strict: no coercion from strings/booleans and no non-finite lengths.
WinderWidth = Annotated[float, Field(ge=700, le=2_000, strict=True, allow_inf_nan=False)]
WinderTread = Annotated[float, Field(ge=200, le=400, strict=True, allow_inf_nan=False)]
WinderFlightSteps = Annotated[int, Field(ge=3, le=24, strict=True)]
WinderNewel = Annotated[float, Field(ge=200, le=500, strict=True, allow_inf_nan=False)]
StairPlacement = Literal["left", "center", "right"]
StairTurn = Literal["left", "right"]

WALL_MM = 250.0
STAIR_CLEARANCE_MM = WALL_MM + 100.0
OPENING_MARGIN_MM = 50.0
# Comfort rule for the quarter-turn flights: 2 × rise + tread (Blondel step formula).
L_STAIR_STRIDE_MM = (550.0, 700.0)
# A winder stair always turns through exactly three 30° treads.
WINDER_COUNT = 3
WINDER_ANGLE_RAD = math.pi / 6
# Winder goings are compared on one arc this far outside the newel square's near side.
WINDER_WALKLINE_OFFSET_MM = 300.0
# Geometric guard far above kernel tolerance: no winder edge may approach a collapsed sliver.
WINDER_MIN_EDGE_MM = 50.0


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
    kind: Literal["straight"] = "straight"


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class LTurnStairRequest:
    """Two straight flights joined by one square quarter-turn landing.

    Flight 1 climbs along +X; the landing is a ``width × width`` square; flight 2 climbs along
    +Y (``turn="left"``) or −Y (``turn="right"``).  The landing counts as one riser, so the
    derived riser is ``floor_height / (lower + upper + 1)``.
    """

    kind: Literal["l_turn"]
    width_mm: StairWidth = 1_000
    tread_depth_mm: StairTread = 280
    lower_step_count: FlightSteps = 8
    upper_step_count: FlightSteps = 8
    turn: StairTurn = "left"
    placement: StairPlacement = "center"
    railing: bool = True
    material_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @property
    def step_count(self) -> int:
        """Total risers between the two floors, the landing included."""
        return self.lower_step_count + self.upper_step_count + 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class UTurnStairRequest:
    """Two equal parallel flights joined by one full-width half-turn landing.

    Flight 1 climbs along +X.  The landing spans both flights and counts as one riser;
    flight 2 returns along -X.  Equal flight counts keep both flights aligned to the same
    bounded landing without accepting an implicit corridor or guessed transition geometry.
    """

    kind: Literal["u_turn"]
    width_mm: StairWidth = 1_000
    tread_depth_mm: StairTread = 280
    flight_step_count: UTurnFlightSteps = 8
    turn: StairTurn = "left"
    placement: StairPlacement = "center"
    railing: bool = True
    material_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @property
    def step_count(self) -> int:
        """Total risers between floors, including the half-turn landing."""
        return 2 * self.flight_step_count + 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class WinderTurnStairRequest:
    """Two perpendicular flights joined by exactly three winder treads around a newel void.

    Flight 1 climbs along +X; three 30° winders turn around an open ``newel × newel`` square;
    flight 2 climbs along +Y (``turn="left"``) or −Y (``turn="right"``).  Every winder is one
    riser, so the derived riser is ``floor_height / (lower + 3 + upper)``.  Railings along a
    winder turn are not modelled, therefore ``railing`` only accepts ``False``.
    """

    kind: Literal["winder_turn"]
    width_mm: WinderWidth = 1_000
    tread_depth_mm: WinderTread = 280
    lower_step_count: WinderFlightSteps = 7
    upper_step_count: WinderFlightSteps = 7
    newel_mm: WinderNewel = 250
    turn: StairTurn = "left"
    placement: StairPlacement = "center"
    railing: Literal[False] = False
    material_id: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @property
    def step_count(self) -> int:
        """Total risers between floors, the three winders included."""
        return self.lower_step_count + WINDER_COUNT + self.upper_step_count

    @property
    def walkline_going_mm(self) -> float:
        """Arc going of every winder on the shared walking line."""
        return (float(self.newel_mm) + WINDER_WALKLINE_OFFSET_MM) * WINDER_ANGLE_RAD


def stair_kind(value: Any) -> str:
    """Historical stored requests have no ``kind`` and are always straight flights."""
    if isinstance(value, dict):
        return str(value.get("kind", "straight"))
    return str(getattr(value, "kind", "straight"))


StairRequest = Annotated[
    Annotated[StraightStairRequest, Tag("straight")]
    | Annotated[LTurnStairRequest, Tag("l_turn")]
    | Annotated[UTurnStairRequest, Tag("u_turn")]
    | Annotated[WinderTurnStairRequest, Tag("winder_turn")],
    Discriminator(stair_kind),
]


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class HouseBoxRequest:
    length_mm: HouseLength
    width_mm: HouseLength
    floor_height_mm: FloorHeight
    floors: FloorCount
    shape: HouseShape = "rectangle"
    stair: StairRequest | None = None
    upper_floor_setback_mm: UpperFloorSetback = 0

    def __post_init__(self) -> None:
        setback = float(self.upper_floor_setback_mm)
        if setback:
            if self.floors < 2:
                raise ValueError("an upper-floor setback requires at least two floors")
            if self.shape != "rectangle":
                raise ValueError("the bounded upper-floor setback requires a rectangular house")
            if (
                float(self.length_mm) - 2 * setback < 2_000
                or float(self.width_mm) - 2 * setback < 2_000
            ):
                raise ValueError(
                    "the setback must leave every upper floor at least 2000 mm wide and long"
                )
        if self.stair is None:
            return
        if self.floors < 2:
            raise ValueError("a stair requires at least two floors")
        if self.shape != "rectangle":
            raise ValueError("the bounded stair builder currently requires a rectangular house")
        if isinstance(self.stair, WinderTurnStairRequest):
            _validate_winder_stair(self)
            return
        if isinstance(self.stair, (LTurnStairRequest, UTurnStairRequest)):
            if not 10 <= self.stair.step_count <= 30:
                raise ValueError(
                    "a turning stair needs 10-30 risers in total (both flights plus the landing)"
                )
            rise = float(self.floor_height_mm) / self.stair.step_count
            if not 120 <= rise <= 220:
                raise ValueError(
                    "floor height divided by the total riser count must produce a 120-220 mm rise"
                )
            stride = 2 * rise + float(self.stair.tread_depth_mm)
            if not L_STAIR_STRIDE_MM[0] <= stride <= L_STAIR_STRIDE_MM[1]:
                raise ValueError("2 × rise + tread must stay within 550-700 mm for a turning stair")
            if isinstance(self.stair, LTurnStairRequest):
                l_stair_layout(self)
            else:
                u_stair_layout(self)
            _validate_stair_against_upper_floor(self)
            return
        rise = float(self.floor_height_mm) / self.stair.step_count
        if not 120 <= rise <= 220:
            raise ValueError("floor height divided by step count must produce a 120-220 mm rise")
        _stair_origin(self)
        _validate_stair_against_upper_floor(self)

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
    if not isinstance(request.stair, StraightStairRequest):  # pragma: no cover - callers prove
        raise ValueError("the house has no straight stair")
    clearance = STAIR_CLEARANCE_MM
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


Rect = tuple[float, float, float, float]  # min_x, min_y, max_x, max_y


def floor_rect(request: HouseBoxRequest, floor_index: int) -> Rect:
    """Return the trusted aligned rectangle for one floor (or the roof at ``floors``)."""
    inset = float(request.upper_floor_setback_mm) if floor_index > 0 else 0.0
    return (
        inset,
        inset,
        float(request.length_mm) - inset,
        float(request.width_mm) - inset,
    )


def _validate_stair_against_upper_floor(request: HouseBoxRequest) -> None:
    """Fail closed when a stair/shaft leaves the reduced upper-floor footprint."""
    if not request.upper_floor_setback_mm or request.stair is None:
        return
    min_floor_x, min_floor_y, max_floor_x, max_floor_y = floor_rect(request, 1)
    for min_x, min_y, max_x, max_y in _opening_rects(request):
        if (
            min_x < min_floor_x + STAIR_CLEARANCE_MM
            or min_y < min_floor_y + STAIR_CLEARANCE_MM
            or max_x > max_floor_x - STAIR_CLEARANCE_MM
            or max_y > max_floor_y - STAIR_CLEARANCE_MM
        ):
            raise ValueError("the stair opening does not fit inside the setback upper floor")


@plain_dataclass(frozen=True, slots=True)
class LStairLayout:
    """Trusted plan-space geometry of one L-turn stair, shared by the CAD plan and 2D plans."""

    turn: StairTurn
    width: float
    tread: float
    rise: float
    lower_steps: int
    upper_steps: int
    lower: Rect
    landing: Rect
    upper: Rect

    @property
    def outline(self) -> list[tuple[float, float]]:
        """Six-corner L outline (flight 1 + landing + flight 2), first corner at flight 1 start."""
        x0, y0, _, y1 = self.lower
        lx0, _, lx1, _ = self.landing
        _, uy0, _, uy1 = self.upper
        if self.turn == "left":
            return [(x0, y0), (lx1, y0), (lx1, uy1), (lx0, uy1), (lx0, y1), (x0, y1)]
        return [(x0, y0), (lx0, y0), (lx0, uy0), (lx1, uy0), (lx1, y1), (x0, y1)]


def l_stair_layout(request: HouseBoxRequest) -> LStairLayout:
    """Place the L footprint inside the house or reject an impossible stair/opening."""
    stair = request.stair
    if not isinstance(stair, LTurnStairRequest):  # pragma: no cover - callers prove this first
        raise ValueError("the house has no L-turn stair")
    length = float(request.length_mm)
    house_width = float(request.width_mm)
    width = float(stair.width_mm)
    tread = float(stair.tread_depth_mm)
    run1 = tread * stair.lower_step_count
    run2 = tread * stair.upper_step_count
    extent_x = run1 + width
    extent_y = width + run2
    clearance = STAIR_CLEARANCE_MM
    min_x = (length - extent_x) / 2
    if stair.placement == "left":
        min_y = clearance
    elif stair.placement == "right":
        min_y = house_width - clearance - extent_y
    else:
        min_y = (house_width - extent_y) / 2
    if (
        min_x < clearance
        or min_x + extent_x > length - clearance
        or min_y < clearance
        or min_y + extent_y > house_width - clearance
    ):
        raise ValueError("the L-turn stair and its opening do not fit inside the house footprint")
    y = min_y if stair.turn == "left" else min_y + run2
    landing_x = min_x + run1
    lower = (min_x, y, landing_x, y + width)
    landing = (landing_x, y, landing_x + width, y + width)
    upper = (
        (landing_x, y + width, landing_x + width, y + width + run2)
        if stair.turn == "left"
        else (landing_x, y - run2, landing_x + width, y)
    )
    return LStairLayout(
        turn=stair.turn,
        width=width,
        tread=tread,
        rise=float(request.floor_height_mm) / stair.step_count,
        lower_steps=stair.lower_step_count,
        upper_steps=stair.upper_step_count,
        lower=lower,
        landing=landing,
        upper=upper,
    )


@plain_dataclass(frozen=True, slots=True)
class UStairLayout:
    """Trusted rectangular footprint for one U-turn stair and its two parallel flights."""

    turn: StairTurn
    width: float
    tread: float
    rise: float
    flight_steps: int
    lower: Rect
    landing: Rect
    upper: Rect

    @property
    def outline(self) -> list[tuple[float, float]]:
        min_x = min(self.lower[0], self.upper[0])
        min_y = self.landing[1]
        max_x = self.landing[2]
        max_y = self.landing[3]
        return [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]


def u_stair_layout(request: HouseBoxRequest) -> UStairLayout:
    """Place a U footprint inside the house or reject an impossible stair/opening."""
    stair = request.stair
    if not isinstance(stair, UTurnStairRequest):  # pragma: no cover - callers prove this first
        raise ValueError("the house has no U-turn stair")
    length = float(request.length_mm)
    house_width = float(request.width_mm)
    width = float(stair.width_mm)
    tread = float(stair.tread_depth_mm)
    run = tread * stair.flight_step_count
    extent_x = run + width
    extent_y = 2 * width
    clearance = STAIR_CLEARANCE_MM
    min_x = (length - extent_x) / 2
    if stair.placement == "left":
        min_y = clearance
    elif stair.placement == "right":
        min_y = house_width - clearance - extent_y
    else:
        min_y = (house_width - extent_y) / 2
    if (
        min_x < clearance
        or min_x + extent_x > length - clearance
        or min_y < clearance
        or min_y + extent_y > house_width - clearance
    ):
        raise ValueError("the U-turn stair and its opening do not fit inside the house footprint")
    landing_x = min_x + run
    lower_y = min_y if stair.turn == "left" else min_y + width
    upper_y = min_y + width if stair.turn == "left" else min_y
    return UStairLayout(
        turn=stair.turn,
        width=width,
        tread=tread,
        rise=float(request.floor_height_mm) / stair.step_count,
        flight_steps=stair.flight_step_count,
        lower=(min_x, lower_y, landing_x, lower_y + width),
        landing=(landing_x, min_y, landing_x + width, min_y + 2 * width),
        upper=(min_x, upper_y, landing_x, upper_y + width),
    )


Polygon = tuple[tuple[float, float], ...]


@plain_dataclass(frozen=True, slots=True)
class WinderStairLayout:
    """Trusted plan-space geometry of one winder stair, shared by the CAD plan and 2D plans.

    ``turn_box`` is the square that holds the three winders plus the open ``newel`` square in
    its inner corner.  Every winder polygon is counter-clockwise for both turn directions, so
    the exact prism extruded from it is never inside-out.
    """

    turn: StairTurn
    width: float
    tread: float
    rise: float
    lower_steps: int
    upper_steps: int
    lower: Rect
    turn_box: Rect
    upper: Rect
    newel: Rect
    winders: tuple[Polygon, ...]

    @property
    def outline(self) -> list[tuple[float, float]]:
        """Six-corner swept footprint; the re-entrant corner is the newel's near corner."""
        x0, y0, _, y1 = self.lower
        _, _, tx1, _ = self.turn_box
        ux0, uy0, _, uy1 = self.upper
        if self.turn == "left":
            return [(x0, y0), (tx1, y0), (tx1, uy1), (ux0, uy1), (ux0, y1), (x0, y1)]
        return [(x0, y0), (ux0, y0), (ux0, uy0), (tx1, uy0), (tx1, y1), (x0, y1)]

    @property
    def opening_rects(self) -> list[Rect]:
        """Two overlapping rectangles whose union is exactly ``outline``."""
        x0, y0, _, y1 = self.lower
        _, ty0, tx1, ty1 = self.turn_box
        ux0, uy0, ux1, uy1 = self.upper
        return [(x0, y0, tx1, y1), (ux0, min(ty0, uy0), ux1, max(ty1, uy1))]


def winder_stair_layout(request: HouseBoxRequest) -> WinderStairLayout:
    """Place the winder footprint inside the house or reject an impossible stair/opening."""
    stair = request.stair
    if not isinstance(stair, WinderTurnStairRequest):  # pragma: no cover - callers prove this
        raise ValueError("the house has no winder-turn stair")
    length = float(request.length_mm)
    house_width = float(request.width_mm)
    width = float(stair.width_mm)
    tread = float(stair.tread_depth_mm)
    newel = float(stair.newel_mm)
    size = width + newel
    run1 = tread * stair.lower_step_count
    run2 = tread * stair.upper_step_count
    extent_x = run1 + size
    extent_y = size + run2
    clearance = STAIR_CLEARANCE_MM
    min_x = (length - extent_x) / 2
    if stair.placement == "left":
        min_y = clearance
    elif stair.placement == "right":
        min_y = house_width - clearance - extent_y
    else:
        min_y = (house_width - extent_y) / 2
    if (
        min_x < clearance
        or min_x + extent_x > length - clearance
        or min_y < clearance
        or min_y + extent_y > house_width - clearance
    ):
        raise ValueError("the winder stair and its opening do not fit inside the house footprint")

    # Canonical left turn in turn-box coordinates.  All riser lines meet in the newel's far
    # corner (0, size); the two inner ones are at 30° and 60°, so all three treads are 30°.
    inner = newel * math.tan(WINDER_ANGLE_RAD)
    outer = size * math.tan(WINDER_ANGLE_RAD)
    inner_1, outer_1 = (inner, width), (outer, 0.0)
    inner_2, outer_2 = (newel, size - inner), (size, size - outer)
    local: tuple[Polygon, ...] = (
        ((0.0, width), (0.0, 0.0), outer_1, inner_1),
        (inner_1, outer_1, (size, 0.0), outer_2, inner_2, (newel, width)),
        (inner_2, outer_2, (size, size), (newel, size)),
    )
    left = stair.turn == "left"
    turn_x = min_x + run1
    turn_y = min_y if left else min_y + run2

    def place(polygon: Polygon) -> Polygon:
        if left:
            return tuple((turn_x + x, turn_y + y) for x, y in polygon)
        # Mirroring reverses the winding, so the vertex order is reversed back.
        return tuple((turn_x + x, turn_y + (size - y)) for x, y in reversed(polygon))

    lower_y = turn_y if left else turn_y + newel
    layout = WinderStairLayout(
        turn=stair.turn,
        width=width,
        tread=tread,
        rise=float(request.floor_height_mm) / stair.step_count,
        lower_steps=stair.lower_step_count,
        upper_steps=stair.upper_step_count,
        lower=(min_x, lower_y, turn_x, lower_y + width),
        turn_box=(turn_x, turn_y, turn_x + size, turn_y + size),
        upper=(
            (turn_x + newel, turn_y + size, turn_x + size, turn_y + size + run2)
            if left
            else (turn_x + newel, min_y, turn_x + size, turn_y)
        ),
        newel=(
            turn_x,
            turn_y + width if left else turn_y,
            turn_x + newel,
            turn_y + size if left else turn_y + newel,
        ),
        winders=tuple(place(polygon) for polygon in local),
    )
    _validate_winder_layout(layout)
    return layout


def _signed_area(polygon: Polygon) -> float:
    return (
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
        )
        / 2
    )


def _edges(polygon: Polygon) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return list(zip(polygon, (*polygon[1:], polygon[0]), strict=True))


def _polygon_is_simple(polygon: Polygon) -> bool:
    """True when no two non-adjacent edges touch."""

    def side(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])

    edges = _edges(polygon)
    for left in range(len(edges)):
        for right in range(left + 2, len(edges)):
            if left == 0 and right == len(edges) - 1:
                continue
            (a, b), (c, d) = edges[left], edges[right]
            if side(a, b, c) * side(a, b, d) <= 0 and side(c, d, a) * side(c, d, b) <= 0:
                return False
    return True


def _validate_winder_layout(layout: WinderStairLayout) -> None:
    """Prove the three treads are simple, face-connected and tile the turn around the newel."""
    tolerance = 1e-6
    size = layout.turn_box[2] - layout.turn_box[0]
    newel = layout.newel[2] - layout.newel[0]
    for polygon in layout.winders:
        if any(math.dist(a, b) < WINDER_MIN_EDGE_MM for a, b in _edges(polygon)):
            raise ValueError("a winder tread edge collapses below the buildable minimum")
        if _signed_area(polygon) <= 0 or not _polygon_is_simple(polygon):
            raise ValueError("a winder tread is not a simple counter-clockwise polygon")
    expected_area = size * size - newel * newel
    if (
        len(layout.winders) != WINDER_COUNT
        or abs(sum(map(_signed_area, layout.winders)) - expected_area) > tolerance * expected_area
    ):
        raise ValueError("the winder treads do not tile the turn around the newel")
    # Every neighbouring pair (including both flights) must share one whole riser edge,
    # otherwise the fuse would silently produce separate solids.
    up_y = layout.upper[1] if layout.turn == "left" else layout.upper[3]
    chain = [
        {(layout.lower[2], layout.lower[1]), (layout.lower[2], layout.lower[3])},
        *(
            set(before) & set(after)
            for before, after in zip(layout.winders, layout.winders[1:], strict=False)
        ),
        {(layout.upper[0], up_y), (layout.upper[2], up_y)},
    ]
    for polygon, entry, leave in zip(layout.winders, chain, chain[1:], strict=False):
        for edge in (entry, leave):
            if len(edge) != 2 or any(
                min(math.dist(point, vertex) for vertex in polygon) > tolerance for point in edge
            ):
                raise ValueError("neighbouring winder treads do not share a riser edge")


def winder_operation_count(request: HouseBoxRequest) -> int:
    """Exact OperationPlan size: shells, openings, roof and every fused transition."""
    stair = request.stair
    assert isinstance(stair, WinderTurnStairRequest)
    transitions = request.floors - 1
    shells = 2 * request.floors  # box + shell per floor
    openings = 2 * 2 * transitions  # two rectangles, box + cut each, per upper floor
    roof = 1
    flights = (2 * stair.step_count - 1) * transitions  # one body per riser, fused into step 1
    return shells + openings + roof + flights


def _validate_winder_stair(request: HouseBoxRequest) -> None:
    """Reject every impossible winder request, including its complete generated plan."""
    stair = request.stair
    assert isinstance(stair, WinderTurnStairRequest)
    if not 10 <= stair.step_count <= 30:
        raise ValueError(
            "a winder stair needs 10-30 risers in total (both flights plus three winders)"
        )
    rise = float(request.floor_height_mm) / stair.step_count
    if not 120 <= rise <= 220:
        raise ValueError(
            "floor height divided by the total riser count must produce a 120-220 mm rise"
        )
    low, high = L_STAIR_STRIDE_MM
    if not low <= 2 * rise + float(stair.tread_depth_mm) <= high:
        raise ValueError("2 × rise + tread must stay within 550-700 mm for a turning stair")
    if not low <= 2 * rise + stair.walkline_going_mm <= high:
        raise ValueError(
            "2 × rise + winder walking-line going must stay within 550-700 mm; change newel_mm"
        )
    winder_stair_layout(request)
    _validate_stair_against_upper_floor(request)
    if winder_operation_count(request) > MAX_PLAN_OPERATIONS:  # pragma: no cover - bounds prove
        raise ValueError(f"the winder house exceeds {MAX_PLAN_OPERATIONS} plan operations")
    # The whole OperationPlan is validated before a job or project can be persisted.
    if len(build(request).operations) != winder_operation_count(request):  # pragma: no cover
        raise ValueError("the winder house plan does not match its derived operation count")


def l_stair_rail_ids(floor_index: int) -> list[str]:
    """Stable rail body ids for one L-turn transition (two per flight, two on the landing)."""
    suffix = f"{floor_index + 1}_{floor_index + 2}"
    return [
        f"rail_lower_inner_{suffix}",
        f"rail_lower_outer_{suffix}",
        f"rail_landing_side_{suffix}",
        f"rail_landing_back_{suffix}",
        f"rail_upper_inner_{suffix}",
        f"rail_upper_outer_{suffix}",
    ]


def u_stair_rail_ids(floor_index: int) -> list[str]:
    """Stable rail body ids for one U-turn transition."""
    suffix = f"{floor_index + 1}_{floor_index + 2}"
    return [
        f"rail_lower_inner_{suffix}",
        f"rail_lower_outer_{suffix}",
        f"rail_landing_left_{suffix}",
        f"rail_landing_back_{suffix}",
        f"rail_landing_right_{suffix}",
        f"rail_upper_inner_{suffix}",
        f"rail_upper_outer_{suffix}",
    ]


def _cut(op_id: str, *, target: str, tool: str) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "boolean",
        "schema_version": 1,
        "op": "cut",
        "target": target,
        "tool": tool,
    }


def _rotate(
    op_id: str, *, target: str, axis: str, angle_deg: float, origin_mm: tuple[float, float, float]
) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "rotate",
        "schema_version": 1,
        "target": target,
        "axis": axis,
        "angle_deg": angle_deg,
        "origin_mm": origin_mm,
    }


def _extrude_polygon(
    op_id: str, *, polygon: Polygon, height_mm: float, z_mm: float
) -> dict[str, object]:
    return {
        "id": op_id,
        "type": "extrude",
        "schema_version": 1,
        "profile": {"kind": "polygon", "points_mm": [list(point) for point in polygon]},
        "height_mm": height_mm,
        "origin_mm": (0.0, 0.0, z_mm),
    }


def _l_stair_operations(
    request: HouseBoxRequest, layout: LStairLayout, floor_index: int
) -> tuple[list[dict[str, object]], list[str]]:
    """One fused exact L flight (steps + landing) and optional exact rail bodies."""
    assert isinstance(request.stair, LTurnStairRequest)
    z = floor_index * float(request.floor_height_mm)
    rise, tread, width = layout.rise, layout.tread, layout.width
    flight_id = f"stair_{floor_index + 1}_{floor_index + 2}"
    first_step = f"{flight_id}_step_1"
    operations: list[dict[str, object]] = []
    lower_x, lower_y, landing_x, _ = layout.lower
    _, _, _, landing_y1 = layout.landing
    total = layout.lower_steps + layout.upper_steps + 1
    for riser in range(1, total + 1):
        if riser <= layout.lower_steps:
            step_id = f"{flight_id}_step_{riser}"
            box = _box(
                step_id,
                width_mm=tread,
                depth_mm=width,
                height_mm=rise * riser,
                origin_mm=(lower_x + tread * (riser - 1), lower_y, z),
            )
        elif riser == layout.lower_steps + 1:
            step_id = f"{flight_id}_landing"
            box = _box(
                step_id,
                width_mm=width,
                depth_mm=width,
                height_mm=rise * riser,
                origin_mm=(landing_x, lower_y, z),
            )
        else:
            k = riser - layout.lower_steps - 1  # 1-based index within flight 2
            step_id = f"{flight_id}_step_{riser - 1}"
            y = landing_y1 + tread * (k - 1) if layout.turn == "left" else lower_y - tread * k
            box = _box(
                step_id,
                width_mm=width,
                depth_mm=tread,
                height_mm=rise * riser,
                origin_mm=(landing_x, y, z),
            )
        operations.append(box)
        if riser > 1:
            operations.append(_fuse(f"join_{step_id}", target=first_step, tool=step_id))
    outputs = [first_step]
    if not request.stair.railing:
        return operations, outputs

    rail = 50.0
    guard = 900.0
    lower_inner_y, lower_outer_y = (
        (lower_y + width - rail, lower_y)
        if layout.turn == "left"
        else (lower_y, lower_y + width - rail)
    )
    run1 = tread * layout.lower_steps
    run2 = tread * layout.upper_steps
    lower_angle = -math.degrees(math.atan2(rise * layout.lower_steps, run1))
    lower_length = math.hypot(run1, rise * layout.lower_steps)
    landing_top = z + rise * (layout.lower_steps + 1)
    upper_angle = math.degrees(math.atan2(rise * layout.upper_steps, run2))
    upper_length = math.hypot(run2, rise * layout.upper_steps)
    ids = l_stair_rail_ids(floor_index)
    lower_inner, lower_outer, landing_side, landing_back, upper_inner, upper_outer = ids
    for rail_id, rail_y in ((lower_inner, lower_inner_y), (lower_outer, lower_outer_y)):
        origin = (lower_x, rail_y, z + guard)
        operations.extend(
            [
                _box(
                    rail_id, width_mm=lower_length, depth_mm=rail, height_mm=rail, origin_mm=origin
                ),
                _rotate(
                    f"slope_{rail_id}",
                    target=rail_id,
                    axis="y",
                    angle_deg=lower_angle,
                    origin_mm=origin,
                ),
            ]
        )
    # Landing guards close the two outer sides that no flight enters or leaves.
    back_y = lower_y if layout.turn == "left" else landing_y1 - rail
    operations.extend(
        [
            _box(
                landing_side,
                width_mm=rail,
                depth_mm=width,
                height_mm=rail,
                origin_mm=(landing_x + width - rail, lower_y, landing_top + guard),
            ),
            _box(
                landing_back,
                width_mm=width,
                depth_mm=rail,
                height_mm=rail,
                origin_mm=(landing_x, back_y, landing_top + guard),
            ),
        ]
    )
    for rail_id, rail_x in ((upper_inner, landing_x), (upper_outer, landing_x + width - rail)):
        if layout.turn == "left":
            origin = (rail_x, landing_y1, landing_top + guard)
            angle = upper_angle
        else:
            # Start at the top end and descend towards the landing along +Y.
            origin = (rail_x, lower_y - run2, landing_top + rise * layout.upper_steps + guard)
            angle = -upper_angle
        operations.extend(
            [
                _box(
                    rail_id, width_mm=rail, depth_mm=upper_length, height_mm=rail, origin_mm=origin
                ),
                _rotate(
                    f"slope_{rail_id}", target=rail_id, axis="x", angle_deg=angle, origin_mm=origin
                ),
            ]
        )
    outputs.extend(ids)
    return operations, outputs


def _u_stair_operations(
    request: HouseBoxRequest, layout: UStairLayout, floor_index: int
) -> tuple[list[dict[str, object]], list[str]]:
    """One fused exact U flight (parallel runs + landing) and optional rail bodies."""
    assert isinstance(request.stair, UTurnStairRequest)
    z = floor_index * float(request.floor_height_mm)
    rise, tread, width = layout.rise, layout.tread, layout.width
    flight_id = f"stair_{floor_index + 1}_{floor_index + 2}"
    first_step = f"{flight_id}_step_1"
    operations: list[dict[str, object]] = []
    lower_x, lower_y, landing_x, _ = layout.lower
    _, landing_y, _, landing_y1 = layout.landing
    upper_x, upper_y, upper_x1, _ = layout.upper
    total = 2 * layout.flight_steps + 1
    for riser in range(1, total + 1):
        if riser <= layout.flight_steps:
            step_id = f"{flight_id}_step_{riser}"
            box = _box(
                step_id,
                width_mm=tread,
                depth_mm=width,
                height_mm=rise * riser,
                origin_mm=(lower_x + tread * (riser - 1), lower_y, z),
            )
        elif riser == layout.flight_steps + 1:
            step_id = f"{flight_id}_landing"
            box = _box(
                step_id,
                width_mm=width,
                depth_mm=2 * width,
                height_mm=rise * riser,
                origin_mm=(landing_x, landing_y, z),
            )
        else:
            k = riser - layout.flight_steps - 1
            step_id = f"{flight_id}_step_{riser - 1}"
            box = _box(
                step_id,
                width_mm=tread,
                depth_mm=width,
                height_mm=rise * riser,
                origin_mm=(upper_x1 - tread * k, upper_y, z),
            )
        operations.append(box)
        if riser > 1:
            operations.append(_fuse(f"join_{step_id}", target=first_step, tool=step_id))
    outputs = [first_step]
    if not request.stair.railing:
        return operations, outputs

    rail = 50.0
    guard = 900.0
    run = tread * layout.flight_steps
    angle = math.degrees(math.atan2(rise * layout.flight_steps, run))
    rail_length = math.hypot(run, rise * layout.flight_steps)
    landing_top = z + rise * (layout.flight_steps + 1)
    ids = u_stair_rail_ids(floor_index)
    (
        lower_inner,
        lower_outer,
        landing_left,
        landing_back,
        landing_right,
        upper_inner,
        upper_outer,
    ) = ids
    lower_inner_y = layout.lower[3] - rail if layout.turn == "left" else layout.lower[1]
    upper_inner_y = layout.upper[1] if layout.turn == "left" else layout.upper[3] - rail
    outer_lower_y = layout.lower[1] if layout.turn == "left" else layout.lower[3] - rail
    outer_upper_y = layout.upper[3] - rail if layout.turn == "left" else layout.upper[1]
    for rail_id, rail_y in ((lower_inner, lower_inner_y), (lower_outer, outer_lower_y)):
        origin = (lower_x, rail_y, z + guard)
        operations.extend(
            [
                _box(
                    rail_id, width_mm=rail_length, depth_mm=rail, height_mm=rail, origin_mm=origin
                ),
                _rotate(
                    f"slope_{rail_id}", target=rail_id, axis="y", angle_deg=-angle, origin_mm=origin
                ),
            ]
        )
    operations.extend(
        [
            _box(
                landing_left,
                width_mm=width,
                depth_mm=rail,
                height_mm=rail,
                origin_mm=(landing_x, landing_y, landing_top + guard),
            ),
            _box(
                landing_back,
                width_mm=rail,
                depth_mm=2 * width,
                height_mm=rail,
                origin_mm=(landing_x + width - rail, landing_y, landing_top + guard),
            ),
            _box(
                landing_right,
                width_mm=width,
                depth_mm=rail,
                height_mm=rail,
                origin_mm=(landing_x, landing_y1 - rail, landing_top + guard),
            ),
        ]
    )
    top_z = z + rise * total + guard
    for rail_id, rail_y in ((upper_inner, upper_inner_y), (upper_outer, outer_upper_y)):
        origin = (upper_x, rail_y, top_z)
        operations.extend(
            [
                _box(
                    rail_id, width_mm=rail_length, depth_mm=rail, height_mm=rail, origin_mm=origin
                ),
                _rotate(
                    f"slope_{rail_id}", target=rail_id, axis="y", angle_deg=angle, origin_mm=origin
                ),
            ]
        )
    outputs.extend(ids)
    return operations, outputs


def _winder_stair_operations(
    request: HouseBoxRequest, layout: WinderStairLayout, floor_index: int
) -> tuple[list[dict[str, object]], list[str]]:
    """One fused exact winder flight: lower boxes, three polygonal prisms, upper boxes."""
    assert isinstance(request.stair, WinderTurnStairRequest)
    z = floor_index * float(request.floor_height_mm)
    rise, tread, width = layout.rise, layout.tread, layout.width
    flight_id = f"stair_{floor_index + 1}_{floor_index + 2}"
    first_step = f"{flight_id}_step_1"
    operations: list[dict[str, object]] = []
    lower_x, lower_y, _, _ = layout.lower
    upper_x, upper_y, _, upper_y1 = layout.upper
    for riser in range(1, request.stair.step_count + 1):
        height = rise * riser
        if riser <= layout.lower_steps:
            step_id = f"{flight_id}_step_{riser}"
            body = _box(
                step_id,
                width_mm=tread,
                depth_mm=width,
                height_mm=height,
                origin_mm=(lower_x + tread * (riser - 1), lower_y, z),
            )
        elif riser <= layout.lower_steps + WINDER_COUNT:
            winder = riser - layout.lower_steps
            step_id = f"{flight_id}_winder_{winder}"
            body = _extrude_polygon(
                step_id, polygon=layout.winders[winder - 1], height_mm=height, z_mm=z
            )
        else:
            k = riser - layout.lower_steps - WINDER_COUNT  # 1-based index within flight 2
            step_id = f"{flight_id}_step_{riser - WINDER_COUNT}"
            body = _box(
                step_id,
                width_mm=width,
                depth_mm=tread,
                height_mm=height,
                origin_mm=(
                    upper_x,
                    upper_y + tread * (k - 1) if layout.turn == "left" else upper_y1 - tread * k,
                    z,
                ),
            )
        operations.append(body)
        if riser > 1:
            operations.append(_fuse(f"join_{step_id}", target=first_step, tool=step_id))
    return operations, [first_step]


def _opening_rects(request: HouseBoxRequest) -> list[Rect]:
    """Upper-floor openings (before margin) that keep the whole stair footprint clear."""
    stair = request.stair
    if isinstance(stair, LTurnStairRequest):
        l_layout = l_stair_layout(request)
        lower_x, lower_y, _, _ = l_layout.lower
        _, _, landing_x1, landing_y1 = l_layout.landing
        return [(lower_x, lower_y, landing_x1, landing_y1), l_layout.upper]
    if isinstance(stair, UTurnStairRequest):
        u_layout = u_stair_layout(request)
        min_x, min_y = u_layout.outline[0]
        max_x, max_y = u_layout.outline[2]
        return [(min_x, min_y, max_x, max_y)]
    if isinstance(stair, WinderTurnStairRequest):
        return winder_stair_layout(request).opening_rects
    assert stair is not None
    x, y = _stair_origin(request)
    run = float(stair.tread_depth_mm) * stair.step_count
    return [(x, y, x + run, y + float(stair.width_mm))]


def _shape_body_operations(
    request: HouseBoxRequest,
    *,
    body_id: str,
    height_mm: float,
    z_mm: float,
    footprint_index: int = 0,
) -> list[dict[str, object]]:
    """Build one exact footprint body at a measured elevation, preserving the canonical shape."""
    min_x, min_y, max_x, max_y = floor_rect(request, footprint_index)
    length = max_x - min_x
    width = max_y - min_y
    if request.shape == "rectangle":
        return [
            _box(
                body_id,
                width_mm=length,
                depth_mm=width,
                height_mm=height_mm,
                origin_mm=(min_x, min_y, z_mm),
            )
        ]
    if request.shape == "l_shape":
        wing = f"{body_id}_side_wing"
        return [
            _box(
                body_id,
                width_mm=length,
                depth_mm=width / 2,
                height_mm=height_mm,
                origin_mm=(0.0, 0.0, z_mm),
            ),
            _box(
                wing,
                width_mm=length / 2,
                depth_mm=width,
                height_mm=height_mm,
                origin_mm=(0.0, 0.0, z_mm),
            ),
            _fuse(f"join_{wing}", target=body_id, tool=wing),
        ]
    third = length / 3
    overlap = min(10.0, third / 100)
    left = f"{body_id}_left_wing"
    right = f"{body_id}_right_wing"
    return [
        _box(
            body_id,
            width_mm=third,
            depth_mm=width,
            height_mm=height_mm,
            origin_mm=(third, 0.0, z_mm),
        ),
        _box(
            left,
            width_mm=third + overlap,
            depth_mm=width / 3,
            height_mm=height_mm,
            origin_mm=(0.0, width * 2 / 3, z_mm),
        ),
        _box(
            right,
            width_mm=third + overlap,
            depth_mm=width / 3,
            height_mm=height_mm,
            origin_mm=(length - third - overlap, width * 2 / 3, z_mm),
        ),
        _fuse(f"join_{left}", target=body_id, tool=left),
        _fuse(f"join_{right}", target=body_id, tool=right),
    ]


def _multifloor_operations(request: HouseBoxRequest) -> tuple[list[dict[str, object]], list[str]]:
    """Build separate footprint shells and optional exact stairs for scene-level visibility."""
    floor_height = float(request.floor_height_mm)
    stair = request.stair
    wall = WALL_MM
    opening_margin = OPENING_MARGIN_MM
    openings = _opening_rects(request) if stair is not None else []
    operations: list[dict[str, object]] = []
    outputs: list[str] = []

    for floor_index in range(request.floors):
        floor_id = f"floor_{floor_index + 1}"
        z = floor_index * floor_height
        operations.extend(
            _shape_body_operations(
                request,
                body_id=floor_id,
                height_mm=floor_height,
                z_mm=z,
                footprint_index=floor_index,
            )
        )
        operations.append(
            {
                "id": f"hollow_{floor_id}",
                "type": "shell",
                "schema_version": 1,
                "target": floor_id,
                "thickness_mm": wall,
                "open_face": {"kind": "face_by_normal", "axis": "z", "sign": "+"},
            }
        )
        if floor_index > 0:
            for opening_index, (min_x, min_y, max_x, max_y) in enumerate(openings):
                # The straight stair keeps its historical single opening id.
                opening_id = f"stair_opening_{floor_index + 1}" + (
                    f"_{opening_index + 1}" if len(openings) > 1 else ""
                )
                operations.extend(
                    [
                        _box(
                            opening_id,
                            width_mm=max_x - min_x + 2 * opening_margin,
                            depth_mm=max_y - min_y + 2 * opening_margin,
                            height_mm=wall + 2,
                            origin_mm=(min_x - opening_margin, min_y - opening_margin, z - 1),
                        ),
                        _cut(f"cut_{opening_id}", target=floor_id, tool=opening_id),
                    ]
                )
        outputs.append(floor_id)

    operations.extend(
        _shape_body_operations(
            request,
            body_id="roof",
            height_mm=wall,
            z_mm=request.floors * floor_height,
            footprint_index=request.floors,
        )
    )
    outputs.append("roof")

    if stair is None:
        return operations, outputs
    if isinstance(stair, LTurnStairRequest):
        l_layout = l_stair_layout(request)
        for floor_index in range(request.floors - 1):
            flight_operations, flight_outputs = _l_stair_operations(request, l_layout, floor_index)
            operations.extend(flight_operations)
            outputs.extend(flight_outputs)
        return operations, outputs
    if isinstance(stair, UTurnStairRequest):
        u_layout = u_stair_layout(request)
        for floor_index in range(request.floors - 1):
            flight_operations, flight_outputs = _u_stair_operations(request, u_layout, floor_index)
            operations.extend(flight_operations)
            outputs.extend(flight_outputs)
        return operations, outputs
    if isinstance(stair, WinderTurnStairRequest):
        winder_layout = winder_stair_layout(request)
        for floor_index in range(request.floors - 1):
            flight_operations, flight_outputs = _winder_stair_operations(
                request, winder_layout, floor_index
            )
            operations.extend(flight_operations)
            outputs.extend(flight_outputs)
        return operations, outputs

    tread = float(stair.tread_depth_mm)
    stair_width = float(stair.width_mm)
    rise = floor_height / stair.step_count
    run = tread * stair.step_count
    x, y = _stair_origin(request)
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

    if isinstance(request.stair, (LTurnStairRequest, UTurnStairRequest)):
        operations, outputs = _multifloor_operations(request)
        u_turn = isinstance(request.stair, UTurnStairRequest)
        return OperationPlan.model_validate(
            {
                "schema_version": 1,
                "goal": (
                    f"{request.floors}-floor house with a U-turn stair"
                    if u_turn
                    else f"{request.floors}-floor house with an L-turn stair"
                ),
                "assumptions": [
                    "All dimensions are millimetres.",
                    "Each floor is a separate exact shell so floor visibility is deterministic.",
                    (
                        "Both flights, the "
                        f"{'half' if u_turn else 'quarter'}-turn landing and the upper-floor "
                        "openings are "
                        "generated from one stair spec; the landing counts as one riser."
                    ),
                ],
                "operations": operations,
                "validation_steps": [
                    "Confirm every floor shell is a valid solid.",
                    "Confirm every upper floor has an "
                    f"{'U' if u_turn else 'L'} opening aligned to both flights.",
                    "Confirm the landing and both flights fuse into one solid per transition.",
                    "Confirm the top step reaches the exact floor-to-floor height.",
                ],
                "expected_outputs": outputs,
            }
        )
    if isinstance(request.stair, WinderTurnStairRequest):
        operations, outputs = _multifloor_operations(request)
        return OperationPlan.model_validate(
            {
                "schema_version": 1,
                "goal": f"{request.floors}-floor house with a winder-turn stair",
                "assumptions": [
                    "All dimensions are millimetres.",
                    "Each floor is a separate exact shell so floor visibility is deterministic.",
                    (
                        "Both flights, three 30-degree winders around an open newel square and "
                        "the upper-floor openings are generated from one stair spec; each winder "
                        "counts as one riser."
                    ),
                    "No newel post, railing, structural or building-code claim is modelled.",
                ],
                "operations": operations,
                "validation_steps": [
                    "Confirm every floor shell is a valid solid.",
                    "Confirm every upper floor has an L opening over the swept stair footprint.",
                    "Confirm both flights and three winders fuse into one solid per transition.",
                    "Confirm the top step reaches the exact floor-to-floor height.",
                ],
                "expected_outputs": outputs,
            }
        )
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

    if request.floors > 1:
        operations, outputs = _multifloor_operations(request)
        return OperationPlan.model_validate(
            {
                "schema_version": 1,
                "goal": f"{request.floors}-floor {request.shape} house with explicit floor shells",
                "assumptions": [
                    "All dimensions are millimetres.",
                    (
                        "Upper levels and the roof use the validated symmetric setback."
                        if request.upper_floor_setback_mm
                        else (
                            "Every level repeats the same validated footprint and measured "
                            "floor height."
                        )
                    ),
                    "No stair, opening or inter-floor circulation is inferred.",
                ],
                "operations": operations,
                "validation_steps": [
                    "Confirm every floor shell is a valid solid at its exact elevation.",
                    "Confirm the roof repeats the validated footprint.",
                    "Confirm no stair or opening was inferred.",
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
