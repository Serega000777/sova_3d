"""Electronics enclosure generator (T-157, F-036): "a case for a Raspberry Pi 4 with a 40 mm fan".

The catalogue (F-035) says what the board is; this turns it into an OperationPlan the kernel
builds exactly: a tray with a floor, walls to the material's thickness and rounded outer
corners; a standoff under every mounting hole, drilled for the board's own screws; a cutout
where every port reaches the outside, with a millimetre of clearance; and a lid with a lip
that drops in, carrying the fan — its opening and its four screw holes — or a row of vents.
Two bodies, `tray` and `lid`, laid side by side for the plate.

Every number is a parameter of the plan, so "make the walls 3 mm" afterwards is one edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.engineering import knowledge as kb
from app.engineering.components import COMPONENTS, Component, Cutout, find

PORT_CLEARANCE_MM = 1.0  # around every port opening
LIP_HEIGHT_MM = 3.0
LIP_CLEARANCE_MM = 0.2  # per side, so the lid drops in without forcing
POST_EMBED_MM = 0.5  # standoffs sink into the floor so the fuse joins volumes, not faces
LID_GAP_MM = 10.0  # between tray and lid on the plate
VENT_SLOT_MM = 2.0
# what a case is built around; a fan or a motor is mounted, not housed
HOUSED_KINDS = ("board", "display", "sensor", "battery")


@dataclass(frozen=True)
class EnclosureRequest:
    component_id: str
    wall_mm: float = 2.0
    clearance_mm: float = 1.0  # around the board
    headroom_mm: float = 2.0  # above the tallest part
    lid: bool = True
    fan_id: str | None = None  # a fan from the catalogue, on the lid
    vents: bool = True  # slots on the lid when there is no fan
    corner_radius_mm: float = 2.0
    material_id: str | None = None


@dataclass(frozen=True)
class Enclosure:
    plan: dict[str, Any]
    outer_mm: tuple[float, float, float]
    inner_mm: tuple[float, float, float]
    posts: int
    cutouts: list[str]
    lid: bool
    fan: str | None
    notes: list[str]


def _op(op_id: str, op_type: str, **params: Any) -> dict[str, Any]:
    return {"id": op_id, "type": op_type, "schema_version": 1, **params}


def _r(value: float) -> float:
    return round(float(value), 3)


def tap_diameter(screw: str, hole_mm: float, material_id: str | None) -> float:
    """The hole to model so the board's screw bites: the KB's thread-forming size when it
    knows the screw, otherwise a little under the board's own hole."""
    fastener = kb.FASTENERS.get(screw.lower())
    if fastener is not None:
        return _r(kb.hole_for(fastener, "tap", material_id))
    return _r(max(hole_mm - 0.3, 1.2))


def _cut_box(
    cutout: Cutout,
    *,
    outer: tuple[float, float, float],
    wall: float,
    board_origin: tuple[float, float, float],
    board_top_z: float,
) -> dict[str, Any] | None:
    """A block through one wall where the port is, a millimetre larger all round."""
    width, depth, height = outer
    bx, by, _ = board_origin
    span = cutout.width_mm + 2 * PORT_CLEARANCE_MM
    tall = cutout.height_mm + 2 * PORT_CLEARANCE_MM
    z0 = board_top_z + cutout.z_mm - PORT_CLEARANCE_MM
    through = wall + 2.0
    if cutout.side in ("+x", "-x"):
        y0 = by + cutout.offset_mm - PORT_CLEARANCE_MM
        x0 = width - wall - 1.0 if cutout.side == "+x" else -1.0
        size = (through, span, tall)
        origin = (x0, y0, z0)
    else:
        x0 = bx + cutout.offset_mm - PORT_CLEARANCE_MM
        y0 = depth - wall - 1.0 if cutout.side == "+y" else -1.0
        size = (span, through, tall)
        origin = (x0, y0, z0)
    if origin[2] + size[2] <= wall:  # entirely inside the floor: nothing to open
        return None
    return {"size": tuple(_r(v) for v in size), "origin": tuple(_r(v) for v in origin)}


def build(request: EnclosureRequest) -> Enclosure:
    component = COMPONENTS.get(request.component_id)
    if component is None:
        raise KeyError(request.component_id)
    fan = COMPONENTS.get(request.fan_id) if request.fan_id else None
    if request.fan_id and fan is None:
        raise KeyError(request.fan_id)
    wall = request.wall_mm
    notes: list[str] = []

    inner_w = component.width_mm + 2 * request.clearance_mm
    inner_d = component.depth_mm + 2 * request.clearance_mm
    inner_h = (
        component.standoff_mm + component.thickness_mm + component.height_mm + request.headroom_mm
    )
    outer = (_r(inner_w + 2 * wall), _r(inner_d + 2 * wall), _r(inner_h + wall))
    board_origin = (
        wall + request.clearance_mm,
        wall + request.clearance_mm,
        wall + component.standoff_mm,
    )
    board_top_z = board_origin[2] + component.thickness_mm

    ops: list[dict[str, Any]] = [
        _op("tray", "create_box", width_mm=outer[0], depth_mm=outer[1], height_mm=outer[2]),
        # hollow first, round after: OCCT thickens a plain box reliably, and the outer
        # corners are still the bounding-box edges once the walls exist
        _op(
            "hollow",
            "shell",
            target="tray",
            thickness_mm=_r(wall),
            open_face={"kind": "face_by_normal", "axis": "z", "sign": "+"},
        ),
    ]
    if request.corner_radius_mm > 0:
        ops.append(
            _op(
                "soften",
                "fillet",
                target="tray",
                edges={"kind": "edges_parallel_to", "axis": "z", "outer": True},
                radius_mm=_r(request.corner_radius_mm),
            )
        )

    # standoffs, each drilled for the board's own screw, then joined to the floor
    tap = (
        tap_diameter(component.screw, component.holes[0].diameter_mm, request.material_id)
        if component.holes
        else 0.0
    )
    posts = 0
    for index, hole in enumerate(component.holes, start=1):
        cx = board_origin[0] + hole.x_mm
        cy = board_origin[1] + hole.y_mm
        if not (wall < cx < outer[0] - wall and wall < cy < outer[1] - wall):
            notes.append(f"mounting hole {index} lies in the wall and got no standoff")
            continue
        post_d = _r(max(hole.diameter_mm + 3.5, 6.0))
        post_h = _r(component.standoff_mm + POST_EMBED_MM)
        ops.append(
            _op(
                f"post_{index}",
                "create_cylinder",
                diameter_mm=post_d,
                height_mm=post_h,
                origin_mm=[_r(cx), _r(cy), _r(wall - POST_EMBED_MM)],
            )
        )
        ops.append(
            _op(
                f"thread_{index}",
                "add_hole",
                target=f"post_{index}",
                face={"kind": "face_by_normal", "axis": "z", "sign": "+"},
                position_mm=[_r(cx), _r(cy)],
                diameter_mm=tap,
                depth_mm=_r(max(component.standoff_mm - 1.0, 2.0)),
            )
        )
        ops.append(_op(f"join_{index}", "boolean", op="fuse", target="tray", tool=f"post_{index}"))
        posts += 1

    # a way out for every port
    opened: list[str] = []
    for index, cutout in enumerate(component.cutouts, start=1):
        box = _cut_box(
            cutout, outer=outer, wall=wall, board_origin=board_origin, board_top_z=board_top_z
        )
        if box is None:
            continue
        ops.append(
            _op(
                f"port_{index}",
                "create_box",
                width_mm=box["size"][0],
                depth_mm=box["size"][1],
                height_mm=box["size"][2],
                origin_mm=list(box["origin"]),
            )
        )
        ops.append(_op(f"open_{index}", "boolean", op="cut", target="tray", tool=f"port_{index}"))
        opened.append(cutout.name)

    expected = ["tray"]
    if request.lid:
        lid_x = outer[0] + LID_GAP_MM
        ops.append(
            _op(
                "lid",
                "create_box",
                width_mm=outer[0],
                depth_mm=outer[1],
                height_mm=_r(wall),
                origin_mm=[_r(lid_x), 0.0, 0.0],
            )
        )
        if request.corner_radius_mm > 0:
            ops.append(
                _op(
                    "soften_lid",
                    "fillet",
                    target="lid",
                    edges={"kind": "edges_parallel_to", "axis": "z", "outer": True},
                    radius_mm=_r(request.corner_radius_mm),
                )
            )
        # the lip: a ring that drops inside the walls
        lip_w = inner_w - 2 * LIP_CLEARANCE_MM
        lip_d = inner_d - 2 * LIP_CLEARANCE_MM
        ops.append(
            _op(
                "lip",
                "create_box",
                width_mm=_r(lip_w),
                depth_mm=_r(lip_d),
                height_mm=_r(LIP_HEIGHT_MM + POST_EMBED_MM),
                origin_mm=[
                    _r(lid_x + wall + LIP_CLEARANCE_MM),
                    _r(wall + LIP_CLEARANCE_MM),
                    _r(wall - POST_EMBED_MM),
                ],
            )
        )
        ops.append(
            _op(
                "lip_inside",
                "create_box",
                width_mm=_r(lip_w - 2 * wall),
                depth_mm=_r(lip_d - 2 * wall),
                height_mm=_r(LIP_HEIGHT_MM + 2.0),
                origin_mm=[
                    _r(lid_x + 2 * wall + LIP_CLEARANCE_MM),
                    _r(2 * wall + LIP_CLEARANCE_MM),
                    _r(wall),
                ],
            )
        )
        ops.append(_op("lip_ring", "boolean", op="cut", target="lip", tool="lip_inside"))
        ops.append(_op("join_lip", "boolean", op="fuse", target="lid", tool="lip"))

        centre = (lid_x + outer[0] / 2, outer[1] / 2)
        if fan is not None and fan.opening_mm:
            room = (inner_w - 2 * wall - 1.0, inner_d - 2 * wall - 1.0)
            if fan.width_mm > room[0] or fan.depth_mm > room[1]:
                notes.append(
                    f"{fan.name} does not fit the lid "
                    f"({room[0]:.0f} x {room[1]:.0f} mm inside the lip)"
                )
            else:
                ops.append(
                    _op(
                        "fan_opening",
                        "create_cylinder",
                        diameter_mm=_r(min(fan.opening_mm)),
                        height_mm=_r(wall + 2.0),
                        origin_mm=[_r(centre[0]), _r(centre[1]), -1.0],
                    )
                )
                ops.append(_op("open_fan", "boolean", op="cut", target="lid", tool="fan_opening"))
                for index, hole in enumerate(fan.holes, start=1):
                    ops.append(
                        _op(
                            f"fan_screw_{index}",
                            "add_hole",
                            target="lid",
                            face={"kind": "face_by_normal", "axis": "z", "sign": "-"},
                            position_mm=[
                                _r(centre[0] - fan.width_mm / 2 + hole.x_mm),
                                _r(centre[1] - fan.depth_mm / 2 + hole.y_mm),
                            ],
                            diameter_mm=_r(hole.diameter_mm + 0.3),
                        )
                    )
        elif component.kind == "display" and component.opening_mm:
            # a display shows through its lid: a window over the glass, a little larger
            win = (component.opening_mm[0] + 1.0, component.opening_mm[1] + 1.0)
            ops.append(
                _op(
                    "window",
                    "create_box",
                    width_mm=_r(win[0]),
                    depth_mm=_r(win[1]),
                    height_mm=_r(wall + 2.0),
                    origin_mm=[
                        _r(lid_x + board_origin[0] + component.width_mm / 2 - win[0] / 2),
                        _r(board_origin[1] + component.depth_mm / 2 - win[1] / 2),
                        -1.0,
                    ],
                )
            )
            ops.append(_op("open_window", "boolean", op="cut", target="lid", tool="window"))
            opened.append("display window")
        elif request.vents:
            slots = 5
            length = _r(inner_w * 0.6)
            pitch = 2 * VENT_SLOT_MM + 2.0
            for index in range(slots):
                y = centre[1] - (slots - 1) / 2 * pitch + index * pitch
                ops.append(
                    _op(
                        f"vent_{index + 1}",
                        "create_box",
                        width_mm=length,
                        depth_mm=VENT_SLOT_MM,
                        height_mm=_r(wall + 2.0),
                        origin_mm=[_r(centre[0] - length / 2), _r(y - VENT_SLOT_MM / 2), -1.0],
                    )
                )
                ops.append(
                    _op(
                        f"vent_cut_{index + 1}",
                        "boolean",
                        op="cut",
                        target="lid",
                        tool=f"vent_{index + 1}",
                    )
                )
        expected.append("lid")

    if component.confidence != "datasheet":
        notes.append(
            f"{component.name}: {component.confidence} dimensions — "
            "check the ports with a caliper before printing"
        )
    goal = f"Enclosure for {component.name}" + (f" with a {fan.name}" if fan else "")
    plan = {
        "schema_version": 1,
        "goal": goal,
        "assumptions": [
            f"walls {wall:g} mm, floor {wall:g} mm, {request.clearance_mm:g} mm around the board",
            f"standoffs {component.standoff_mm:g} mm tall for {component.screw} screws",
            f"{request.headroom_mm:g} mm above the tallest part ({component.height_mm:g} mm)",
        ],
        "required_clarifications": [],
        "operations": ops,
        "validation_steps": [
            f"outer size {outer[0]:g} x {outer[1]:g} x {outer[2]:g} mm",
            f"{posts} standoffs on the board's hole pattern",
            f"{len(opened)} port openings",
        ],
        "expected_outputs": expected,
    }
    return Enclosure(
        plan=plan,
        outer_mm=outer,
        inner_mm=(_r(inner_w), _r(inner_d), _r(inner_h)),
        posts=posts,
        cutouts=opened,
        lid=request.lid,
        fan=fan.id if fan else None,
        notes=notes,
    )


# --- the sentence -----------------------------------------------------------------------------

_CUES = re.compile(
    r"(корпус|коробк\w+ для|бокс для|кейс|enclosure|\bcase\b|housing|\bbox for\b)", re.IGNORECASE
)
_NO_LID = re.compile(r"(без крышки|no lid|without (a )?lid|open top)", re.IGNORECASE)
# "вентилятор 40 мм" and "a 30mm fan": the size may come before or after the word
_FAN = re.compile(
    r"(?:вентилятор\w*|кулер\w*|\bfan\b)\D{0,12}(\d{2})?"
    r"|(\d{2})\s*(?:mm|мм)?\s*(?:вентилятор\w*|кулер\w*|\bfan\b)",
    re.IGNORECASE,
)
_WALL = re.compile(r"(стенк\w*|wall\w*)\D{0,12}(\d+(?:[.,]\d+)?)\s*(mm|мм)", re.IGNORECASE)


def parse(prompt: str) -> EnclosureRequest | None:
    """ "Корпус под Raspberry Pi 4 с вентилятором 40 мм" -> the request, or None."""
    if not _CUES.search(prompt):
        return None
    component = find(prompt, kinds=HOUSED_KINDS)
    if component is None:
        return None
    fan_id = None
    fan = _FAN.search(prompt)
    if fan:
        size = fan.group(1) or fan.group(2)
        fan_id = "fan-30" if size == "30" else "fan-40"
    wall = _WALL.search(prompt)
    return EnclosureRequest(
        component_id=component.id,
        wall_mm=float(wall.group(2).replace(",", ".")) if wall else 2.0,
        lid=not _NO_LID.search(prompt),
        fan_id=fan_id,
    )


def component_for(request: EnclosureRequest) -> Component:
    return COMPONENTS[request.component_id]
