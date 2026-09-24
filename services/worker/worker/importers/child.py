"""Sandbox child entrypoint: `python -m worker.importers.child <format> <path>` -> JSON."""

from __future__ import annotations

import sys
from pathlib import Path

from worker.importers.dae import parse_dae_file
from worker.importers.gltf import parse_gltf_file
from worker.importers.mesh import parse_mesh_file
from worker.importers.threemf import parse_3mf_file
from worker.importers.usdz import parse_usdz_file
from worker.importers.zipsafe import UnsafeArchiveError
from worker.report import ImportFailure, ImportMetadata, ImportResult

MESH_FORMATS = ("stl", "obj", "ply")
SCENE_FORMATS = ("glb", "gltf")


def parse(format_id: str, path: Path) -> ImportMetadata:
    if format_id in MESH_FORMATS:
        return parse_mesh_file(path, format_id)
    if format_id in SCENE_FORMATS:
        return parse_gltf_file(path, format_id)
    if format_id == "3mf":
        return parse_3mf_file(path)
    if format_id == "dae":
        return parse_dae_file(path)
    if format_id == "usdz":
        return parse_usdz_file(path)
    raise ValueError(f"unsupported format {format_id!r}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: child <format> <path>", file=sys.stderr)
        return 2
    format_id, path = argv[0], Path(argv[1])
    try:
        result = ImportResult(ok=True, metadata=parse(format_id, path))
    except UnsafeArchiveError as exc:
        result = ImportResult(
            ok=False, error=ImportFailure(code="unsafe_archive", message=str(exc))
        )
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        result = ImportResult(
            ok=False,
            error=ImportFailure(code="parse_failed", message=f"{type(exc).__name__}: {exc}"),
        )
    sys.stdout.write(result.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
