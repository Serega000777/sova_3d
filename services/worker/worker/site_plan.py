"""Deterministic real-scale meshes for a bounded house-site composition.

All coordinates are platform millimetres.  The plot is centred on XY, terrain elevations are
ordered south-west, south-east, north-east, north-west, and every mesh is closed so it remains
exportable through the ordinary scene pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, cast

import numpy as np
import trimesh


def _export(mesh: trimesh.Trimesh) -> bytes:
    payload = cast(Any, mesh).export(file_type="stl")
    if isinstance(payload, str):
        return payload.encode()
    if isinstance(payload, bytes | bytearray):
        return bytes(payload)
    raise TypeError("trimesh returned an unsupported STL payload")


def _box(
    extents: tuple[float, float, float], centre: tuple[float, float, float]
) -> trimesh.Trimesh:
    mesh = cast(trimesh.Trimesh, trimesh.creation.box(extents=extents))
    mesh.apply_translation(np.asarray(centre, dtype=np.float64))
    return mesh


def _terrain_elevation(
    x: float,
    y: float,
    length_mm: float,
    width_mm: float,
    elevations: tuple[float, float, float, float],
) -> float:
    """Interpolate the same SW-SE-NE / SW-NE-NW triangles emitted by terrain."""
    u = (x + length_mm / 2) / length_mm
    v = (y + width_mm / 2) / width_mm
    if v <= u:
        return elevations[0] * (1 - u) + elevations[1] * (u - v) + elevations[2] * v
    return elevations[0] * (1 - v) + elevations[2] * u + elevations[3] * (v - u)


def _segment_prism(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    width_mm: float,
    height_mm: float,
) -> trimesh.Trimesh:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1:
        raise ValueError("path segments must be at least 1 mm long")
    nx, ny = -dy / length * width_mm / 2, dx / length * width_mm / 2
    vertices = np.asarray(
        [
            [start[0] + nx, start[1] + ny, start[2]],
            [start[0] - nx, start[1] - ny, start[2]],
            [end[0] - nx, end[1] - ny, end[2]],
            [end[0] + nx, end[1] + ny, end[2]],
            [start[0] + nx, start[1] + ny, start[2] + height_mm],
            [start[0] - nx, start[1] - ny, start[2] + height_mm],
            [end[0] - nx, end[1] - ny, end[2] + height_mm],
            [end[0] + nx, end[1] + ny, end[2] + height_mm],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            [0, 2, 1],
            [0, 3, 2],
            [4, 5, 6],
            [4, 6, 7],
            [0, 1, 5],
            [0, 5, 4],
            [1, 2, 6],
            [1, 6, 5],
            [2, 3, 7],
            [2, 7, 6],
            [3, 0, 4],
            [3, 4, 7],
        ],
        dtype=np.int64,
    )
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def build_terrain_stl(length_mm: float, width_mm: float, elevations_mm: Iterable[float]) -> bytes:
    elevations = tuple(float(value) for value in elevations_mm)
    if not (1_000 <= length_mm <= 200_000 and 1_000 <= width_mm <= 200_000):
        raise ValueError("plot dimensions must be between 1000 and 200000 mm")
    if len(elevations) != 4 or any(not math.isfinite(value) for value in elevations):
        raise ValueError("terrain needs four finite corner elevations")
    if max(elevations) - min(elevations) > 10_000:
        raise ValueError("terrain corner elevation range exceeds 10000 mm")
    half_x, half_y = length_mm / 2, width_mm / 2
    bottom = min(elevations) - 200.0
    vertices = np.asarray(
        [
            [-half_x, -half_y, elevations[0]],
            [half_x, -half_y, elevations[1]],
            [half_x, half_y, elevations[2]],
            [-half_x, half_y, elevations[3]],
            [-half_x, -half_y, bottom],
            [half_x, -half_y, bottom],
            [half_x, half_y, bottom],
            [-half_x, half_y, bottom],
        ],
        dtype=np.float64,
    )
    faces = np.asarray(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [1, 5, 6],
            [1, 6, 2],
            [2, 6, 7],
            [2, 7, 3],
            [3, 7, 4],
            [3, 4, 0],
        ],
        dtype=np.int64,
    )
    return _export(trimesh.Trimesh(vertices=vertices, faces=faces, process=False))


def build_pad_stl(length_mm: float, width_mm: float, height_mm: float) -> bytes:
    if min(length_mm, width_mm, height_mm) <= 0 or max(length_mm, width_mm) > 60_000:
        raise ValueError("house pad dimensions are outside the supported range")
    return _export(_box((length_mm, width_mm, height_mm), (0, 0, height_mm / 2)))


def build_path_stl(
    points_mm: Iterable[Iterable[float]],
    width_mm: float,
    *,
    plot_length_mm: float,
    plot_width_mm: float,
    elevations_mm: Iterable[float],
) -> bytes:
    points = [tuple(float(value) for value in point) for point in points_mm]
    if len(points) < 2 or len(points) > 16 or any(len(point) != 2 for point in points):
        raise ValueError("a site path needs 2 to 16 XY points")
    if not 300 <= width_mm <= 5_000:
        raise ValueError("path width must be between 300 and 5000 mm")
    elevations = tuple(float(value) for value in elevations_mm)
    if len(elevations) != 4:
        raise ValueError("terrain needs four corner elevations")
    parts: list[trimesh.Trimesh] = []
    for start, end in zip(points, points[1:], strict=False):
        start_z = _terrain_elevation(start[0], start[1], plot_length_mm, plot_width_mm, elevations)
        end_z = _terrain_elevation(end[0], end[1], plot_length_mm, plot_width_mm, elevations)
        parts.append(
            _segment_prism(
                (start[0], start[1], start_z),
                (end[0], end[1], end_z),
                width_mm,
                60.0,
            )
        )
    return _export(cast(trimesh.Trimesh, trimesh.util.concatenate(parts)))


def build_fence_stl(
    length_mm: float,
    width_mm: float,
    sides: Iterable[str],
    height_mm: float,
    post_spacing_mm: float,
    elevations_mm: Iterable[float],
) -> bytes:
    selected = tuple(dict.fromkeys(str(side) for side in sides))
    if not selected or any(side not in {"north", "east", "south", "west"} for side in selected):
        raise ValueError("fence sides are invalid")
    if not 400 <= height_mm <= 4_000 or not 1_000 <= post_spacing_mm <= 5_000:
        raise ValueError("fence dimensions are outside the supported range")
    half_x, half_y = length_mm / 2, width_mm / 2
    elevations = tuple(float(value) for value in elevations_mm)
    if len(elevations) != 4:
        raise ValueError("terrain needs four corner elevations")
    definitions = {
        "south": ((-half_x, -half_y), (half_x, -half_y)),
        "east": ((half_x, -half_y), (half_x, half_y)),
        "north": ((half_x, half_y), (-half_x, half_y)),
        "west": ((-half_x, half_y), (-half_x, -half_y)),
    }
    parts: list[trimesh.Trimesh] = []
    post = 100.0
    rail = 70.0
    for side in selected:
        start, end = definitions[side]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        count = max(1, math.ceil(length / post_spacing_mm))
        for index in range(count + 1):
            ratio = index / count
            x, y = start[0] + dx * ratio, start[1] + dy * ratio
            ground = _terrain_elevation(x, y, length_mm, width_mm, elevations)
            parts.append(_box((post, post, height_mm), (x, y, ground + height_mm / 2)))
        for z in (height_mm * 0.35, height_mm * 0.75):
            start_z = _terrain_elevation(start[0], start[1], length_mm, width_mm, elevations)
            end_z = _terrain_elevation(end[0], end[1], length_mm, width_mm, elevations)
            parts.append(
                _segment_prism(
                    (start[0], start[1], start_z + z),
                    (end[0], end[1], end_z + z),
                    rail,
                    rail,
                )
            )
    return _export(cast(trimesh.Trimesh, trimesh.util.concatenate(parts)))
