"""Deterministic low-poly furniture assets for the interior scene catalogue.

Every item is built in platform millimetres, centred on XY and resting on Z=0. The output
is deliberately simple, editable mesh geometry rather than a decorative UI-only thumbnail.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import numpy as np
import trimesh

FurnitureKind = Literal["chair", "table", "sofa", "bed", "cabinet"]


def _box(size: tuple[float, float, float], centre: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = cast(trimesh.Trimesh, trimesh.creation.box(extents=size))
    mesh.apply_translation(np.asarray(centre, dtype=np.float64))
    return mesh


def build_stl(kind: FurnitureKind, width: float, depth: float, height: float) -> bytes:
    if min(width, depth, height) <= 0 or max(width, depth, height) > 10_000:
        raise ValueError("furniture dimensions must be positive and at most 10000 mm")
    parts: list[trimesh.Trimesh]
    if kind == "table":
        top = max(24.0, min(height * 0.08, 60.0))
        leg = max(35.0, min(width, depth) * 0.08)
        parts = [_box((width, depth, top), (0, 0, height - top / 2))]
        for x in (-width / 2 + leg, width / 2 - leg):
            for y in (-depth / 2 + leg, depth / 2 - leg):
                parts.append(_box((leg, leg, height - top), (x, y, (height - top) / 2)))
    elif kind == "chair":
        seat_z = height * 0.46
        seat = max(28.0, height * 0.05)
        leg = max(28.0, min(width, depth) * 0.09)
        parts = [_box((width, depth, seat), (0, 0, seat_z))]
        for x in (-width / 2 + leg, width / 2 - leg):
            for y in (-depth / 2 + leg, depth / 2 - leg):
                parts.append(_box((leg, leg, seat_z), (x, y, seat_z / 2)))
        parts.append(
            _box(
                (width, max(35.0, depth * 0.09), height - seat_z),
                (0, depth / 2 - max(35.0, depth * 0.09) / 2, (height + seat_z) / 2),
            )
        )
    elif kind == "sofa":
        base_h = height * 0.28
        seat_h = height * 0.18
        arm = max(90.0, width * 0.08)
        parts = [
            _box((width, depth, base_h), (0, 0, base_h / 2)),
            _box((width - arm * 2, depth * 0.72, seat_h), (0, -depth * 0.07, base_h + seat_h / 2)),
            _box(
                (width - arm * 2, depth * 0.2, height - base_h),
                (0, depth * 0.4, (height + base_h) / 2),
            ),
            _box((arm, depth, height * 0.58), (-width / 2 + arm / 2, 0, height * 0.29)),
            _box((arm, depth, height * 0.58), (width / 2 - arm / 2, 0, height * 0.29)),
        ]
    elif kind == "bed":
        frame_h = height * 0.35
        parts = [
            _box((width, depth, frame_h), (0, 0, frame_h / 2)),
            _box(
                (width * 0.94, depth * 0.9, height - frame_h),
                (0, -depth * 0.03, (height + frame_h) / 2),
            ),
            _box(
                (width, max(45.0, depth * 0.05), height * 1.8),
                (0, depth / 2 - max(45.0, depth * 0.05) / 2, height * 0.9),
            ),
        ]
    elif kind == "cabinet":
        shell = max(24.0, min(width, depth) * 0.04)
        parts = [
            _box((width, depth, shell), (0, 0, shell / 2)),
            _box((width, depth, shell), (0, 0, height - shell / 2)),
            _box((shell, depth, height), (-width / 2 + shell / 2, 0, height / 2)),
            _box((shell, depth, height), (width / 2 - shell / 2, 0, height / 2)),
            _box((width - shell * 2, shell, height), (0, depth / 2 - shell / 2, height / 2)),
        ]
    else:
        raise ValueError(f"unsupported furniture kind {kind!r}")
    merged = cast(trimesh.Trimesh, trimesh.util.concatenate(parts))
    exported = cast(Any, merged).export(file_type="stl")
    if isinstance(exported, str):
        return exported.encode()
    if isinstance(exported, bytes | bytearray):
        return bytes(exported)
    raise TypeError("trimesh returned an unsupported STL payload")
