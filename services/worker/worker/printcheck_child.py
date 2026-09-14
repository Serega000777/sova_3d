"""Sandbox child for print analysis.

Usage: `python -m worker.printcheck_child <stl> <config.json> [--optimize]`.

config.json = {"printer": {...PrinterProfile}, "material": {...MaterialProfile},
               "apply_to": "<path.stl>" (optional; with --optimize writes the rotated mesh)}
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import trimesh

from worker import printcheck
from worker.importers.common import as_single_mesh


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: printcheck_child <mesh.stl> <config.json> [--optimize]", file=sys.stderr)
        return 2
    mesh_path, config_path = Path(argv[0]), Path(argv[1])
    optimize = "--optimize" in argv
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        printer = printcheck.PrinterProfile.model_validate(config.get("printer", {}))
        material = printcheck.MaterialProfile.model_validate(config.get("material", {}))
        loaded = trimesh.load(
            io.BytesIO(mesh_path.read_bytes()), file_type="stl", force="mesh", process=False
        )
        mesh = as_single_mesh(loaded)
        if mesh is None or mesh.is_empty:
            raise ValueError("no mesh geometry")
        mesh = mesh.copy()
        mesh.merge_vertices()
        if optimize:
            analysis = printcheck.optimize(mesh, printer=printer, material=material)
            apply_to = config.get("apply_to")
            if apply_to and analysis.recommended is not None:
                rotated = printcheck.apply_orientation(mesh, analysis.recommended.orientation)
                exported = rotated.export(file_type="stl")
                if not isinstance(exported, bytes | bytearray):
                    raise TypeError("STL export did not return bytes")
                Path(apply_to).write_bytes(bytes(exported))
        else:
            analysis = printcheck.analyze(mesh, printer=printer, material=material)
        sys.stdout.write(json.dumps({"ok": True, "analysis": analysis.model_dump(mode="json")}))
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        sys.stdout.write(
            json.dumps(
                {"ok": False, "code": "analysis_failed", "message": f"{type(exc).__name__}: {exc}"}
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
