"""AI Material (T-138, F-009): the construction adapts to the material it will be printed in.

The user picks PLA, PETG, ABS, TPU or ASA and the part changes where the material demands
it: walls and floors grow to the material's structural minimum — pockets move and shrink
so every wall and divider makes the number — screw holes are re-sized for how that material
prints, and a brittle material gets its sharp vertical corners rounded. Everything is a
set_parameter or a fillet on the version's own plan, so the edit endpoint validates it and
the kernel replays it like any other change; nothing here touches a mesh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.engineering import knowledge as kb

Language = Literal["ru", "en"]

MIN_POCKET_MM = 4.0  # a compartment narrower than this is not worth keeping


@dataclass
class Adaptation:
    operations: list[dict[str, Any]] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    wall_mm: float = 0.0


def _num(op: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(op.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _vec(op: dict[str, Any], key: str) -> list[float]:
    raw = op.get(key) or [0.0, 0.0, 0.0]
    return [float(v) for v in raw] + [0.0] * (3 - len(raw))


def _set(op_id: str, parameter: str, value: float) -> dict[str, Any]:
    return {
        "type": "set_parameter",
        "operation": op_id,
        "parameter": parameter,
        "value": round(value, 3),
    }


def _pockets(operations: list[dict[str, Any]], body_id: str) -> list[dict[str, Any]]:
    """Boxes cut out of the body: the compartments whose walls the material decides."""
    tools = {
        op.get("tool")
        for op in operations
        if op.get("type") == "boolean" and op.get("op") == "cut" and op.get("target") == body_id
    }
    return [op for op in operations if op.get("type") == "create_box" and op.get("id") in tools]


def adapt(
    operations: list[dict[str, Any]],
    *,
    material_id: str,
    from_material_id: str | None,
    undersize_from: float | None = None,
    undersize_to: float | None = None,
    nozzle_mm: float = kb.DEFAULT_NOZZLE_MM,
    language: Language = "en",
) -> Adaptation:
    """The operations to append so `operations` suits `material_id`, and what they change."""
    ru = language == "ru"
    material = kb.material(material_id)
    result = Adaptation(wall_mm=kb.recommended_wall_mm(material.id, "structural", nozzle_mm))
    wall = result.wall_mm

    # --- screw holes: what this material does to a hole ---------------------------------------
    shrink_from = (
        kb.material(from_material_id).hole_undersize_mm
        if undersize_from is None
        else undersize_from
    )
    shrink_to = material.hole_undersize_mm if undersize_to is None else undersize_to
    delta = round(shrink_to - shrink_from, 2)
    if abs(delta) >= 0.05:
        for op in operations:
            if op.get("type") != "add_hole":
                continue
            new_d = round(_num(op, "diameter_mm") + delta, 2)
            result.operations.append(_set(str(op["id"]), "diameter_mm", new_d))
        holes = sum(1 for op in operations if op.get("type") == "add_hole")
        if holes:
            result.changes.append(
                f"Отверстия ({holes}) {delta:+g} мм по диаметру: {material.name} печатает их "
                f"с усадкой {shrink_to:g} мм"
                if ru
                else f"{holes} hole(s) {delta:+g} mm in diameter: {material.name} prints them "
                f"{shrink_to:g} mm small"
            )

    # --- walls, floors and dividers -----------------------------------------------------------
    bodies = [
        op
        for op in operations
        if op.get("type") == "create_box"
        and op.get("origin_mm") in (None, [0, 0, 0], [0.0, 0.0, 0.0])
    ]
    creator = next((op for op in bodies if not _is_tool(operations, str(op["id"]))), None)
    if creator is not None:
        width, depth, height = (
            _num(creator, "width_mm"),
            _num(creator, "depth_mm"),
            _num(creator, "height_mm"),
        )
        pockets = _pockets(operations, str(creator["id"]))
        boxes = {
            str(p["id"]): [
                _vec(p, "origin_mm"),
                [_num(p, "width_mm"), _num(p, "depth_mm"), _num(p, "height_mm")],
            ]
            for p in pockets
        }
        moved = 0
        too_small: list[str] = []
        for pocket_id, (origin, size) in boxes.items():
            new_origin = list(origin)
            new_size = list(size)
            for axis, span in ((0, width), (1, depth)):
                lo, hi = origin[axis], origin[axis] + size[axis]
                # nearest obstacle on each side: the outer wall or a neighbouring pocket
                left_obstacle, left_is_pocket = 0.0, False
                right_obstacle, right_is_pocket = span, False
                for other_id, (o_origin, o_size) in boxes.items():
                    if other_id == pocket_id or not _overlaps(
                        origin, size, o_origin, o_size, 1 - axis
                    ):
                        continue
                    o_lo, o_hi = o_origin[axis], o_origin[axis] + o_size[axis]
                    if o_hi <= lo + 1e-6 and o_hi > left_obstacle:
                        left_obstacle, left_is_pocket = o_hi, True
                    if o_lo >= hi - 1e-6 and o_lo < right_obstacle:
                        right_obstacle, right_is_pocket = o_lo, True
                deficit_left = wall - (lo - left_obstacle)
                deficit_right = wall - (right_obstacle - hi)
                if deficit_left > 1e-6:
                    lo += deficit_left / 2 if left_is_pocket else deficit_left
                if deficit_right > 1e-6:
                    hi -= deficit_right / 2 if right_is_pocket else deficit_right
                new_origin[axis] = lo
                new_size[axis] = hi - lo
            floor = max(origin[2], wall + 1.0)  # a floor is a wall that also carries the load
            if floor > origin[2] + 1e-6:
                new_origin[2] = floor
                new_size[2] = max(size[2] - (floor - origin[2]), 1.0)  # the top stays where it was
            if min(new_size[0], new_size[1]) < MIN_POCKET_MM:
                too_small.append(pocket_id)
                continue
            for axis, name in enumerate(("origin_x_mm", "origin_y_mm", "origin_z_mm")):
                if abs(new_origin[axis] - origin[axis]) > 1e-6:
                    result.operations.append(_set(pocket_id, name, new_origin[axis]))
            for axis, name in enumerate(("width_mm", "depth_mm", "height_mm")):
                if abs(new_size[axis] - size[axis]) > 1e-6:
                    result.operations.append(_set(pocket_id, name, new_size[axis]))
            if new_origin != origin or new_size != size:
                moved += 1
        if moved:
            result.changes.append(
                f"Стенки и дно не тоньше {wall:g} мм для {material.name}: "
                f"{moved} секц. сдвинуты и уменьшены"
                if ru
                else f"Walls and floor at least {wall:g} mm for {material.name}: "
                f"{moved} compartment(s) moved and shrunk"
            )
        if too_small:
            result.skipped.append(
                f"{len(too_small)} секц. стали бы уже {MIN_POCKET_MM:g} мм — оставлены как есть"
                if ru
                else f"{len(too_small)} compartment(s) would get narrower than "
                f"{MIN_POCKET_MM:g} mm — left as they are"
            )

        # --- brittle materials: no sharp vertical corners --------------------------------------
        if material.impact == "low" and not any(op.get("type") == "fillet" for op in operations):
            radius = round(min(1.5, 0.1 * min(v for v in (width, depth, height) if v > 0)), 2)
            if radius >= 0.5:
                result.operations.append(
                    {
                        "type": "fillet",
                        "target": str(creator["id"]),
                        "edges": {"kind": "edges_parallel_to", "axis": "z", "outer": True},
                        "radius_mm": radius,
                    }
                )
                result.changes.append(
                    f"{material.name} хрупкий: вертикальные рёбра скруглены на {radius:g} мм"
                    if ru
                    else f"{material.name} is brittle: vertical edges rounded to {radius:g} mm"
                )

    if not result.operations and not result.skipped:
        result.changes.append(
            f"Конструкция уже подходит для {material.name}."
            if ru
            else f"The part already suits {material.name}."
        )
    return result


def _is_tool(operations: list[dict[str, Any]], op_id: str) -> bool:
    return any(op.get("type") == "boolean" and op.get("tool") == op_id for op in operations)


def _overlaps(
    origin: list[float],
    size: list[float],
    other_origin: list[float],
    other_size: list[float],
    axis: int,
) -> bool:
    """Two pockets face each other across a divider only if they overlap along the other axis."""
    lo, hi = origin[axis], origin[axis] + size[axis]
    o_lo, o_hi = other_origin[axis], other_origin[axis] + other_size[axis]
    return min(hi, o_hi) - max(lo, o_lo) > 1e-6
