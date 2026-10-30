"""Deterministic printable parts for bounded functional mechanisms."""

from __future__ import annotations

from typing import cast

import numpy as np
import trimesh


def _box(size: tuple[float, float, float], centre: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = cast(trimesh.Trimesh, trimesh.creation.box(extents=size))
    mesh.apply_translation(np.asarray(centre, dtype=np.float64))
    return mesh


def _sleeve(
    x0: float, x1: float, inner: float, outer: float, *, z_mm: float = 0
) -> trimesh.Trimesh:
    mesh = cast(
        trimesh.Trimesh,
        trimesh.creation.annulus(
            inner,
            outer,
            segment=np.asarray([[x0, 0, 0], [x1, 0, 0]], dtype=np.float64),
            sections=48,
        ),
    )
    mesh.apply_translation(np.asarray([0, 0, z_mm], dtype=np.float64))
    return mesh


def _stl(parts: list[trimesh.Trimesh]) -> bytes:
    mesh = (
        parts[0]
        if len(parts) == 1
        else cast(trimesh.Trimesh, trimesh.boolean.union(parts, engine="manifold"))
    )
    if mesh is None or not mesh.is_watertight:
        raise ValueError("mechanism parts did not form a watertight solid")
    payload = mesh.export(file_type="stl")
    if not isinstance(payload, bytes):
        raise ValueError("mechanism STL export did not return bytes")
    return payload


def build_hinged_lid(
    *,
    width_mm: float,
    depth_mm: float,
    base_height_mm: float,
    lid_thickness_mm: float,
    pin_diameter_mm: float,
    clearance_mm: float,
) -> dict[str, bytes]:
    """Build base, moving lid and removable pin around one exact X-axis revolute joint."""
    values = (
        width_mm,
        depth_mm,
        base_height_mm,
        lid_thickness_mm,
        pin_diameter_mm,
        clearance_mm,
    )
    if any(not np.isfinite(value) or value <= 0 for value in values):
        raise ValueError("mechanism dimensions must be finite and positive")
    pin_radius = pin_diameter_mm / 2
    sleeve_wall = max(1.2, pin_diameter_mm * 0.3)
    sleeve_inner = pin_radius + clearance_mm
    sleeve_outer = sleeve_inner + sleeve_wall
    if base_height_mm < sleeve_outer * 1.1:
        raise ValueError("base height is too small for the requested hinge")

    gap = max(0.4, clearance_mm)
    centre_length = width_mm * 0.44
    side_length = (width_mm - centre_length - gap * 2) / 2
    if side_length <= sleeve_wall:
        raise ValueError("hinge width is too small for three knuckles")
    centre_x0 = -centre_length / 2
    centre_x1 = centre_length / 2
    left_x0 = -width_mm / 2
    left_x1 = centre_x0 - gap
    right_x0 = centre_x1 + gap
    right_x1 = width_mm / 2

    base = _stl(
        [
            _box((width_mm, depth_mm, base_height_mm), (0, depth_mm / 2, base_height_mm / 2)),
            _sleeve(left_x0, left_x1, sleeve_inner, sleeve_outer, z_mm=base_height_mm),
            _sleeve(right_x0, right_x1, sleeve_inner, sleeve_outer, z_mm=base_height_mm),
        ]
    )
    lid = _stl(
        [
            _box((width_mm, depth_mm, lid_thickness_mm), (0, depth_mm / 2, lid_thickness_mm / 2)),
            _sleeve(centre_x0, centre_x1, sleeve_inner, sleeve_outer),
        ]
    )
    pin_mesh = cast(
        trimesh.Trimesh,
        trimesh.creation.cylinder(
            radius=pin_radius,
            segment=np.asarray(
                [[-width_mm / 2 - 1, 0, 0], [width_mm / 2 + 1, 0, 0]], dtype=np.float64
            ),
            sections=48,
        ),
    )
    return {"base": base, "lid": lid, "pin": _stl([pin_mesh])}


# The lid must bear on the side walls and stay under the guide lips by at least this much.
SLIDING_MIN_BEARING_MM = 1.0
SLIDING_MIN_RETENTION_MM = 0.8


def sliding_lid_layout(
    *,
    width_mm: float,
    depth_mm: float,
    base_height_mm: float,
    wall_mm: float,
    floor_mm: float,
    lid_thickness_mm: float,
    guide_width_mm: float,
    lip_overhang_mm: float,
    lip_thickness_mm: float,
    clearance_mm: float,
) -> dict[str, float]:
    """Validate a sliding-lid box fail-closed and return its derived millimetre layout."""
    values = (
        width_mm,
        depth_mm,
        base_height_mm,
        wall_mm,
        floor_mm,
        lid_thickness_mm,
        guide_width_mm,
        lip_overhang_mm,
        lip_thickness_mm,
        clearance_mm,
    )
    if any(not np.isfinite(value) or value <= 0 for value in values):
        raise ValueError("mechanism dimensions must be finite and positive")
    if floor_mm >= base_height_mm - 1:
        raise ValueError("floor is too thick for the base height")
    if width_mm - 2 * wall_mm < 5 or depth_mm - 2 * wall_mm < 5:
        raise ValueError("walls leave no usable cavity")
    bearing = wall_mm - guide_width_mm - clearance_mm
    if bearing < SLIDING_MIN_BEARING_MM:
        raise ValueError("lid would not bear on the side walls; widen walls or narrow guides")
    retention = lip_overhang_mm - clearance_mm
    if retention < SLIDING_MIN_RETENTION_MM:
        raise ValueError("guide lips do not overhang the lid enough to retain it")
    half = width_mm / 2
    lid_half_width = half - guide_width_mm - clearance_mm
    channel_top = base_height_mm + lid_thickness_mm + clearance_mm
    return {
        "lid_width_mm": lid_half_width * 2,
        "lid_depth_mm": depth_mm - wall_mm - clearance_mm,
        "lid_y_mm": wall_mm + clearance_mm,
        "lid_z_mm": base_height_mm,
        "channel_top_mm": channel_top,
        "overall_height_mm": channel_top + lip_thickness_mm,
        "lip_inner_x_mm": half - guide_width_mm - lip_overhang_mm,
        "bearing_mm": bearing,
        "retention_mm": retention,
    }


def build_sliding_lid(
    *,
    width_mm: float,
    depth_mm: float,
    base_height_mm: float,
    wall_mm: float,
    floor_mm: float,
    lid_thickness_mm: float,
    guide_width_mm: float,
    lip_overhang_mm: float,
    lip_thickness_mm: float,
    clearance_mm: float,
) -> dict[str, bytes]:
    """Build an open box with retaining guide lips and a separate lid sliding along +Y.

    The base spans x in [-W/2, W/2], y in [0, D]. The lid is modelled at its own origin
    (x centred, y in [0, lid depth], z in [0, thickness]); the scene places it at
    ``(0, lid_y_mm, lid_z_mm)``, resting on the side walls under the lips with ``clearance_mm``
    to every guide surface. It leaves through the open front end (+Y).
    """
    layout = sliding_lid_layout(
        width_mm=width_mm,
        depth_mm=depth_mm,
        base_height_mm=base_height_mm,
        wall_mm=wall_mm,
        floor_mm=floor_mm,
        lid_thickness_mm=lid_thickness_mm,
        guide_width_mm=guide_width_mm,
        lip_overhang_mm=lip_overhang_mm,
        lip_thickness_mm=lip_thickness_mm,
        clearance_mm=clearance_mm,
    )
    half = width_mm / 2
    top = layout["overall_height_mm"]
    channel_top = layout["channel_top_mm"]
    parts = [
        _box((width_mm, depth_mm, floor_mm), (0, depth_mm / 2, floor_mm / 2)),
        _box((width_mm, wall_mm, base_height_mm), (0, wall_mm / 2, base_height_mm / 2)),
        _box(
            (width_mm, wall_mm, base_height_mm),
            (0, depth_mm - wall_mm / 2, base_height_mm / 2),
        ),
        # back stop closes the lid channel behind the lid
        _box((width_mm, wall_mm, channel_top), (0, wall_mm / 2, channel_top / 2)),
    ]
    for sign in (-1, 1):
        parts.extend(
            [
                _box(
                    (wall_mm, depth_mm, base_height_mm),
                    (sign * (half - wall_mm / 2), depth_mm / 2, base_height_mm / 2),
                ),
                # guide riser, full height so every union below overlaps by volume
                _box(
                    (guide_width_mm, depth_mm, top),
                    (sign * (half - guide_width_mm / 2), depth_mm / 2, top / 2),
                ),
                # retaining lip above the lid channel
                _box(
                    (guide_width_mm + lip_overhang_mm, depth_mm, lip_thickness_mm),
                    (
                        sign * (half - (guide_width_mm + lip_overhang_mm) / 2),
                        depth_mm / 2,
                        channel_top + lip_thickness_mm / 2,
                    ),
                ),
            ]
        )
    lid_depth = layout["lid_depth_mm"]
    lid = _box(
        (layout["lid_width_mm"], lid_depth, lid_thickness_mm),
        (0, lid_depth / 2, lid_thickness_mm / 2),
    )
    return {"base": _stl(parts), "lid": _stl([lid])}
