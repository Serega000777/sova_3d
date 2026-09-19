"""AI Optimize (T-145, F-007): make the part lighter without making it weak.

"Make it lighter" on a parametric part means one thing the kernel can do exactly: hollow
it to a wall the material can carry (`shell`), open on the face it prints on so nothing
inside needs support, and keep the metal-to-plastic places solid — a boss stays around
every screw hole. The result is an edit on the version's own plan, previewed like any
other, with the mass before and after so the user sees what the change is worth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.engineering import knowledge as kb

Language = Literal["ru", "en"]
Opening = Literal["bottom", "top", "none"]
Load = Literal["cosmetic", "structural", "load_bearing"]

MIN_HOLLOW_EXTENT_MM = 12.0  # thinner than this there is nothing worth hollowing
BOSS_WALL_MM = 2.0  # material kept around a screw hole inside the hollow


@dataclass
class Optimization:
    operations: list[dict[str, Any]] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    wall_mm: float = 0.0
    density_g_cm3: float = 0.0


def _num(op: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(op.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _creator(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The body the part is made of: the first creator that is not a boolean tool."""
    tools = {op.get("tool") for op in operations if op.get("type") == "boolean"}
    return next(
        (
            op
            for op in operations
            if op.get("type") in ("create_box", "create_cylinder", "extrude")
            and op.get("id") not in tools
        ),
        None,
    )


def _extents(creator: dict[str, Any]) -> tuple[float, float, float]:
    kind = creator.get("type")
    if kind == "create_box":
        return _num(creator, "width_mm"), _num(creator, "depth_mm"), _num(creator, "height_mm")
    if kind == "create_cylinder":
        d = _num(creator, "diameter_mm")
        return d, d, _num(creator, "height_mm")
    profile = creator.get("profile") or {}
    if profile.get("kind") == "rectangle":
        return _num(profile, "width_mm"), _num(profile, "depth_mm"), _num(creator, "height_mm")
    if profile.get("kind") == "circle":
        d = _num(profile, "diameter_mm")
        return d, d, _num(creator, "height_mm")
    return 0.0, 0.0, _num(creator, "height_mm")


def lighten(
    operations: list[dict[str, Any]],
    *,
    material_id: str | None,
    load: Load = "structural",
    opening: Opening = "bottom",
    wall_mm: float | None = None,
    nozzle_mm: float = kb.DEFAULT_NOZZLE_MM,
    language: Language = "en",
) -> Optimization:
    """The operations to append so the part is hollow to a wall it can carry."""
    ru = language == "ru"
    material = kb.material(material_id)
    wall = wall_mm if wall_mm is not None else kb.recommended_wall_mm(material.id, load, nozzle_mm)
    result = Optimization(wall_mm=wall, density_g_cm3=kb.DENSITY_G_CM3.get(material.id, 1.24))

    if any(op.get("type") == "shell" for op in operations):
        result.changes.append("Деталь уже полая." if ru else "The part is already hollow.")
        return result
    creator = _creator(operations)
    if creator is None:
        result.skipped.append(
            "Нет параметрического тела — облегчить нечего."
            if ru
            else "No parametric body — nothing to hollow."
        )
        return result
    width, depth, height = _extents(creator)
    smallest = min(v for v in (width, depth, height) if v > 0) if any((width, depth, height)) else 0
    if smallest < MIN_HOLLOW_EXTENT_MM or 2 * wall + 2 >= smallest:
        result.skipped.append(
            f"Слишком тонкая деталь для полости со стенкой {wall:g} мм — оставлена сплошной."
            if ru
            else f"Too thin to hollow with a {wall:g} mm wall — left solid."
        )
        return result
    body_id = str(creator["id"])

    # the hollow, open on the face the part prints on
    shell: dict[str, Any] = {"type": "shell", "target": body_id, "thickness_mm": wall}
    if opening != "none":
        shell["open_face"] = {
            "kind": "face_by_normal",
            "axis": "z",
            "sign": "-" if opening == "bottom" else "+",
        }
    result.operations.append(shell)
    where = (
        {"bottom": "открытая снизу", "top": "открытая сверху", "none": "закрытая"}[opening]
        if ru
        else {"bottom": "open at the bottom", "top": "open at the top", "none": "enclosed"}[opening]
    )
    result.changes.append(
        f"Полость со стенкой {wall:g} мм ({material.name}, {where})"
        if ru
        else f"Hollowed to a {wall:g} mm wall ({material.name}, {where})"
    )

    # screw holes keep a solid boss: the hollow must not swallow the thread
    holes = [
        op for op in operations if op.get("type") == "add_hole" and op.get("target") == body_id
    ]
    used = {str(op.get("id")) for op in operations}
    origin = list(creator.get("origin_mm") or [0.0, 0.0, 0.0])
    bossed = 0
    for index, hole in enumerate(holes, start=1):
        position = list(hole.get("position_mm") or [0, 0])
        face = hole.get("face") or {}
        if face.get("axis") != "z" or len(position) != 2:
            continue  # bosses are modelled for holes drilled from the top; others stay as they are
        boss_id = f"boss_{index}"
        while boss_id in used:  # never collide with an id the plan already has
            boss_id += "_1"
        used.add(boss_id)
        result.operations.append(
            {
                "type": "create_cylinder",
                "id": boss_id,
                "diameter_mm": round(_num(hole, "diameter_mm") + 2 * BOSS_WALL_MM, 3),
                "height_mm": height,
                "origin_mm": [position[0], position[1], float(origin[2])],
                "axis": "z",
            }
        )
        result.operations.append(
            {"type": "boolean", "op": "fuse", "target": body_id, "tool": boss_id}
        )
        # the fuse fills the hole: drill it again through the boss
        result.operations.append({k: v for k, v in hole.items() if k != "id"})
        bossed += 1
    if bossed:
        result.changes.append(
            f"Вокруг {bossed} отверст. оставлены бобышки {BOSS_WALL_MM:g} мм"
            if ru
            else f"{bossed} hole(s) keep a {BOSS_WALL_MM:g} mm boss around them"
        )
    return result


def mass_g(volume_mm3: float, density_g_cm3: float) -> float:
    return round(volume_mm3 / 1000.0 * density_g_cm3, 1)
