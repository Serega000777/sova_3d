"""Deterministic, headless PNG thumbnails for canonical model assets.

The worker cannot assume OpenGL, a window server, or a GPU.  This renderer projects a
bounded triangle sample into an isometric view and paints it with a simple directional
light.  It is deliberately a preview artifact, never a geometry conversion.
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from worker import sandbox
from worker.exporters import _load_platform_mesh

WIDTH = 480
HEIGHT = 320
MAX_FACES = 12_000
SUPERSAMPLE = 2


def render_png(
    source_path: Path,
    source_format: str,
    *,
    limits: sandbox.SandboxLimits = sandbox.DEFAULT_LIMITS,
) -> bytes:
    """Render an untrusted model in the same bounded parser sandbox as import/export."""
    with tempfile.TemporaryDirectory(prefix="thumbnail-render-") as tmp:
        output_path = Path(tmp) / "thumbnail.png"
        outcome = sandbox.run(
            "worker.thumbnail",
            [source_format, str(source_path), str(output_path)],
            input_path=source_path,
            limits=limits,
            cwd=output_path.parent,
        )
        if not outcome.ok:
            failure = outcome.failure.value if outcome.failure is not None else "failed"
            raise ValueError(f"thumbnail sandbox {failure}: {outcome.message}")
        payload = outcome.output or {}
        if not payload.get("ok") or not output_path.is_file():
            raise ValueError(str(payload.get("message", "thumbnail renderer produced no image")))
        return output_path.read_bytes()


def _render_png(source_path: Path, source_format: str) -> bytes:
    mesh, _ = _load_platform_mesh(source_path, source_format)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if vertices.size == 0 or faces.size == 0:
        raise ValueError("the model has no triangles to preview")
    if not np.isfinite(vertices).all():
        raise ValueError("the model contains non-finite coordinates")

    if len(faces) > MAX_FACES:
        indices = np.linspace(0, len(faces) - 1, MAX_FACES, dtype=np.int64)
        faces = faces[indices]

    centre = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    points = vertices - centre
    # Camera from +X, -Y, +Z.  These fixed orthonormal axes make output stable across runs.
    screen_x = np.asarray([0.83205, 0.55470, 0.0])
    screen_y = np.asarray([-0.30151, 0.45227, 0.83916])
    depth_axis = np.cross(screen_x, screen_y)
    projected = np.column_stack((points @ screen_x, points @ screen_y))
    depth = points @ depth_axis

    low = projected.min(axis=0)
    high = projected.max(axis=0)
    span = np.maximum(high - low, 1e-9)
    scale = min((WIDTH * 0.78) / span[0], (HEIGHT * 0.78) / span[1]) * SUPERSAMPLE
    canvas_w, canvas_h = WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE
    pixels = np.empty_like(projected)
    pixels[:, 0] = (projected[:, 0] - (low[0] + high[0]) / 2) * scale + canvas_w / 2
    pixels[:, 1] = canvas_h / 2 - (projected[:, 1] - (low[1] + high[1]) / 2) * scale

    image = Image.new("RGB", (canvas_w, canvas_h), "#0d0f12")
    draw = ImageDraw.Draw(image)
    for y in range(int(canvas_h * 0.2), canvas_h, 48 * SUPERSAMPLE):
        draw.line((0, y, canvas_w, y), fill="#171a1f", width=1)

    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    light = np.asarray([0.35, -0.45, 0.82])
    light /= np.linalg.norm(light)
    intensity = np.clip(0.48 + 0.52 * np.abs(normals @ light), 0.35, 1.0)
    face_depth = depth[faces].mean(axis=1)

    # Painter's algorithm: far faces first. Face lighting preserves form without exposing
    # arbitrary triangulation diagonals as if they were authored model edges.
    for face_index in np.argsort(face_depth):
        face = faces[face_index]
        polygon = [(float(pixels[index, 0]), float(pixels[index, 1])) for index in face]
        shade = float(intensity[face_index])
        base = np.asarray([236, 232, 224], dtype=np.float64)
        colour = tuple(int(value) for value in np.clip(base * shade, 0, 255))
        draw.polygon(polygon, fill=colour)

    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _child(source_format: str, source_path: Path, output_path: Path) -> dict[str, Any]:
    output_path.write_bytes(_render_png(source_path, source_format))
    return {"ok": True, "width": WIDTH, "height": HEIGHT}


if __name__ == "__main__":
    import sys

    try:
        result = _child(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(result))
