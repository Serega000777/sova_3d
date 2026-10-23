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
    mesh = parts[0] if len(parts) == 1 else cast(
        trimesh.Trimesh, trimesh.boolean.union(parts, engine="manifold")
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
