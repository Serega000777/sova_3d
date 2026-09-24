"""Preview actual mesh cross-sections at printer layer heights (F-054, first stage).

These are geometric contours, not extrusion paths or machine-ready G-code. Infill,
supports, temperatures and retraction require a separate print-plan stage.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from worker import sandbox
from worker.importers.common import as_single_mesh
from worker.printcheck import PrinterProfile
from worker.sandbox import SandboxLimits

PREVIEW_LIMITS = SandboxLimits(wall_seconds=180, max_output_bytes=8 * 1024 * 1024)
MAX_PREVIEW_LAYERS = 48
MAX_LAYERS = 10000


def preview(mesh: trimesh.Trimesh, printer: PrinterProfile) -> dict[str, Any]:
    if printer.technology != "fdm":
        raise ValueError("layer preview currently supports FDM printers only")
    if mesh.is_empty or not mesh.is_watertight:
        raise ValueError("repair the mesh into a closed solid before slicing")
    if printer.layer_height_mm <= 0 or printer.layer_height_mm > printer.nozzle_mm * 0.8:
        raise ValueError("layer height must be at most 80% of the nozzle diameter")
    bounds = np.asarray(mesh.bounds, dtype=float)
    extents = bounds[1] - bounds[0]
    if not np.isfinite(bounds).all() or (extents <= 0).any():
        raise ValueError("mesh bounds are invalid")
    if (extents[0] > printer.bed_x_mm or extents[1] > printer.bed_y_mm) and (
        extents[1] > printer.bed_x_mm or extents[0] > printer.bed_y_mm
    ):
        raise ValueError("model exceeds the printer bed in X/Y; cut it into parts first")
    if extents[2] > printer.bed_z_mm:
        raise ValueError("model exceeds the printer height; cut it into parts first")
    total = math.ceil(float(extents[2]) / printer.layer_height_mm)
    if total > MAX_LAYERS:
        raise ValueError("too many layers; use a larger layer height")
    indices = (
        sorted(
            {
                round(i * (total - 1) / min(total - 1, MAX_PREVIEW_LAYERS - 1))
                for i in range(min(total, MAX_PREVIEW_LAYERS))
            }
        )
        if total > 1
        else [0]
    )
    # Section through the centre of each deposited layer, never exactly on a mesh face.
    heights = [
        min((index + 0.5) * printer.layer_height_mm, float(extents[2]) - 1e-6) for index in indices
    ]
    sections = mesh.section_multiplane(
        plane_origin=bounds[0], plane_normal=[0, 0, 1], heights=heights
    )
    layers: list[dict[str, Any]] = []
    for index, height, section in zip(indices, heights, sections, strict=True):
        paths: list[list[list[float]]] = []
        if section is not None:
            for curve in section.discrete:
                points = np.asarray(curve, dtype=float)
                if len(points) < 4 or not np.allclose(points[0], points[-1], atol=1e-4):
                    continue
                # Preview only: bound JSON size for detailed organic meshes.
                if len(points) > 1200:
                    points = points[np.linspace(0, len(points) - 1, 1200, dtype=int)]
                paths.append(np.round(points[:, :2], 3).tolist())
        layers.append({"index": index + 1, "z_mm": round(height, 3), "paths": paths})
    return {
        "layer_height_mm": printer.layer_height_mm,
        "total_layers": total,
        "bounds_mm": [round(float(value), 3) for value in extents],
        "sampled_layers": layers,
        "preview_only": True,
    }


def preview_file(mesh_path: Path, printer: PrinterProfile) -> dict[str, Any]:
    config = mesh_path.with_suffix(".slice.json")
    config.write_text(json.dumps(printer.model_dump()), encoding="utf-8")
    outcome = sandbox.run(
        "worker.slicing_child",
        [str(mesh_path), str(config)],
        input_path=mesh_path,
        limits=PREVIEW_LIMITS,
    )
    if not outcome.ok:
        raise ValueError(outcome.message)
    result = outcome.output or {}
    if not result.get("ok"):
        raise ValueError(str(result.get("message", "could not create the layer preview")))
    return dict(result["preview"])


def load_stl(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(
        io.BytesIO(path.read_bytes()), file_type="stl", force="mesh", process=False
    )
    mesh = as_single_mesh(loaded)
    if mesh is None:
        raise ValueError("no mesh geometry")
    mesh.merge_vertices()
    return mesh
