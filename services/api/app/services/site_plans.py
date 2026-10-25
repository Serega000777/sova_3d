"""Validation for bounded plot/terrain/path/fence composition around an exact house."""

from __future__ import annotations

import math
from typing import Any

from app.api.errors import ConflictError, ValidationFailedError
from app.models.core import Project
from app.models.versioning import ProjectVersion

SITE_PLAN_JOB = "compose_site_plan"
SITE_NODE_IDS = frozenset(
    {"site_root", "site_house", "site_terrain", "site_house_pad", "site_path", "site_fence"}
)


def _terrain_elevation(
    x: float,
    y: float,
    length_mm: float,
    width_mm: float,
    elevations: list[float],
) -> float:
    u = (x + length_mm / 2) / length_mm
    v = (y + width_mm / 2) / width_mm
    if v <= u:
        return elevations[0] * (1 - u) + elevations[1] * (u - v) + elevations[2] * v
    return elevations[0] * (1 - v) + elevations[2] * u + elevations[3] * (v - u)


def house_request(version: ProjectVersion) -> dict[str, Any]:
    provenance = version.provenance or {}
    house_box = provenance.get("house_box")
    request = house_box.get("request") if isinstance(house_box, dict) else None
    if not isinstance(request, dict):
        raise ValidationFailedError(
            "site composition requires a house created by the exact house wizard"
        )
    try:
        length = float(request["length_mm"])
        width = float(request["width_mm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailedError("the house lineage has invalid dimensions") from exc
    if not all(math.isfinite(value) and 2_000 <= value <= 50_000 for value in (length, width)):
        raise ValidationFailedError("the house lineage has invalid dimensions")
    return {**request, "length_mm": length, "width_mm": width}


def base_house_nodes(version: ProjectVersion) -> list[dict[str, Any]]:
    """Recover only the house subtree from one canonical prior site composition.

    Recomposition replaces terrain, pad, path and fence assets. It must never silently discard
    arbitrary objects that a buyer added beside the house, so any non-house node outside the
    canonical service subtree fails closed.
    """
    from app.services import scenes

    nodes = scenes.stored_nodes(version)
    if not isinstance((version.provenance or {}).get("site_plan"), dict):
        return nodes
    by_id = {str(node.get("id")): node for node in nodes}
    required = {"site_root", "site_house", "site_terrain", "site_house_pad", "site_path"}
    if not required <= set(by_id):
        raise ValidationFailedError("the existing site scene is incomplete and cannot be rebuilt")
    if (
        by_id["site_root"].get("kind") != "group"
        or by_id["site_root"].get("parent_id") is not None
        or by_id["site_house"].get("kind") != "group"
        or by_id["site_house"].get("parent_id") != "site_root"
    ):
        raise ValidationFailedError("the existing site hierarchy cannot be rebuilt safely")
    for node_id in required - {"site_root", "site_house"}:
        if by_id[node_id].get("kind") != "object" or by_id[node_id].get("parent_id") != "site_root":
            raise ValidationFailedError("the existing site hierarchy cannot be rebuilt safely")
    if "site_fence" in by_id and (
        by_id["site_fence"].get("kind") != "object"
        or by_id["site_fence"].get("parent_id") != "site_root"
    ):
        raise ValidationFailedError("the existing site hierarchy cannot be rebuilt safely")

    def belongs_to_house(node_id: str) -> bool:
        visited: set[str] = set()
        parent_id = by_id[node_id].get("parent_id")
        while parent_id is not None:
            parent = str(parent_id)
            if parent == "site_house":
                return True
            if parent in visited or parent not in by_id:
                return False
            visited.add(parent)
            parent_id = by_id[parent].get("parent_id")
        return False

    house_nodes: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id"))
        if node_id in SITE_NODE_IDS:
            continue
        if not belongs_to_house(node_id):
            raise ValidationFailedError(
                "remove added site objects before rebuilding the composition",
                {"scene_node_id": node_id},
            )
        copied = dict(node)
        if copied.get("parent_id") == "site_house":
            copied["parent_id"] = None
        house_nodes.append(copied)
    if not any(node.get("kind") == "object" for node in house_nodes):
        raise ValidationFailedError("the existing site scene has no house geometry to preserve")
    return house_nodes


def validate_spec(
    *, project: Project, version: ProjectVersion, spec: dict[str, Any]
) -> dict[str, Any]:
    if project.head_version_id != version.id:
        raise ConflictError(
            "the project changed; reload before composing the site",
            {"head_version_id": str(project.head_version_id)},
        )
    base_house_nodes(version)
    request = house_request(version)
    plot_length = float(spec["plot_length_mm"])
    plot_width = float(spec["plot_width_mm"])
    house_x = float(spec["house_x_mm"])
    house_y = float(spec["house_y_mm"])
    angle = math.radians(float(spec["house_rotation_deg"]))
    if not all(
        math.isfinite(value) for value in (plot_length, plot_width, house_x, house_y, angle)
    ):
        raise ValidationFailedError("site dimensions and placement must be finite")
    elevations = [float(value) for value in spec["corner_elevations_mm"]]
    if len(elevations) != 4 or any(not math.isfinite(value) for value in elevations):
        raise ValidationFailedError("terrain needs four finite corner elevations")
    if max(elevations) - min(elevations) > 10_000:
        raise ValidationFailedError("terrain corner elevation range exceeds 10000 mm")
    house_length, house_width = request["length_mm"], request["width_mm"]
    span_x = abs(math.cos(angle)) * house_length + abs(math.sin(angle)) * house_width
    span_y = abs(math.sin(angle)) * house_length + abs(math.cos(angle)) * house_width
    margin = 500.0
    if abs(house_x) + span_x / 2 + margin > plot_length / 2:
        raise ValidationFailedError("the house and a 500 mm margin must fit inside the plot length")
    if abs(house_y) + span_y / 2 + margin > plot_width / 2:
        raise ValidationFailedError("the house and a 500 mm margin must fit inside the plot width")
    path = spec["path_points_mm"]
    if not 2 <= len(path) <= 16:
        raise ValidationFailedError("a site path needs 2 to 16 points")
    previous: tuple[float, float] | None = None
    for point in path:
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValidationFailedError("path coordinates must be finite")
        if abs(x) > plot_length / 2 or abs(y) > plot_width / 2:
            raise ValidationFailedError("every path point must stay inside the plot")
        if previous is not None and math.hypot(x - previous[0], y - previous[1]) < 1:
            raise ValidationFailedError("path segments must be at least 1 mm long")
        previous = (x, y)
    fence_sides = spec["fence_sides"]
    if len(fence_sides) != len(set(fence_sides)):
        raise ValidationFailedError("fence sides must be unique")
    cosine, sine = math.cos(angle), math.sin(angle)
    footprint = [
        (
            house_x + cosine * x - sine * y,
            house_y + sine * x + cosine * y,
        )
        for x in (-house_length / 2, house_length / 2)
        for y in (-house_width / 2, house_width / 2)
    ]
    ground_levels = [
        _terrain_elevation(x, y, plot_length, plot_width, elevations)
        for x, y in [*footprint, (house_x, house_y)]
    ]
    house_z = max(ground_levels) + 100.0
    pad_bottom = min(ground_levels) - 200.0
    return {
        **spec,
        "house": request,
        "house_z_mm": house_z,
        "pad_bottom_mm": pad_bottom,
        "pad_height_mm": house_z - pad_bottom,
    }
