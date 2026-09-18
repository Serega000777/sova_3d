"""STEP/IGES import (T-022): the OCCT kernel reads it, the platform reports it.

CAD files are B-Rep, not meshes, so they do not go through trimesh at all — the geometry
service reads them and hands back the same bodies it would from a plan: a `.brep` (the
parametric source the platform keeps) and a `.stl` (what everything downstream renders and
checks). The binary runs in the sandbox like any other parser, because an uploaded STEP
file is exactly as untrusted as an uploaded mesh.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from worker import geometry as kernel
from worker.report import (
    BBox,
    ImportFailure,
    ImportMetadata,
    ImportResult,
    MeshStats,
    Severity,
    Warning,
)

FORMATS = frozenset({"step", "stp", "iges", "igs"})
CANONICAL = {"step": "step", "stp": "step", "iges": "iges", "igs": "iges"}


def import_cad(path: Path, format_id: str, out_dir: Path | None = None) -> ImportResult:
    """Read a STEP/IGES file into canonical mm; `out_dir` keeps the converted bodies."""
    if format_id not in FORMATS:
        return ImportResult(
            ok=False, error=ImportFailure(code="unsupported_format", message=format_id)
        )
    with tempfile.TemporaryDirectory(prefix="cad-") as tmp:
        target = out_dir or Path(tmp)
        result = kernel.import_cad(path, CANONICAL[format_id], target)

    if not result.ok or not result.bodies:
        error = result.error
        return ImportResult(
            ok=False,
            error=ImportFailure(
                code=error.code if error else "cad_empty",
                message=error.message if error else "the file contains no geometry",
            ),
        )

    # STEP and IGES are millimetres by convention in every CAD package we target, and the
    # kernel reports in mm; an explicit unit in the file header is honoured by OCCT itself.
    main = result.bodies[0]
    warnings: list[Warning] = []
    if len(result.bodies) > 1:
        warnings.append(
            Warning(
                code="multiple_bodies",
                severity=Severity.info,
                message=f"the file contains {len(result.bodies)} separate bodies",
                details={"bodies": ", ".join(body.name for body in result.bodies)},
            )
        )
    if not main.valid:
        warnings.append(
            Warning(
                code="invalid_solid",
                severity=Severity.warning,
                message="the imported shape is not a valid solid; repair before printing",
                details={"body": main.name},
            )
        )
    if main.solids == 0:
        warnings.append(
            Warning(
                code="surface_model",
                severity=Severity.warning,
                message="the file is a surface model, not a solid; it has no printable volume",
                details={"faces": main.faces},
            )
        )

    return ImportResult(
        ok=True,
        metadata=ImportMetadata(
            format=CANONICAL[format_id],
            representation="mesh",  # what the platform stores downstream
            units="mm",
            unit_source="file",
            source_units="mm",
            scale_to_mm=1.0,
            bbox=BBox(min=tuple(main.bbox_mm.min), max=tuple(main.bbox_mm.max)),
            mesh=MeshStats(
                vertices=main.vertices,
                faces=main.faces,
                bodies=max(main.solids, 1),
                watertight=main.valid and main.solids > 0,
                winding_consistent=main.valid,
                volume_mm3=main.volume_mm3,
                surface_area_mm2=main.surface_area_mm2,
                euler_number=0,
                degenerate_faces=0,
                duplicate_faces=0,
            ),
            file_metadata={"kernel": result.kernel, "edges": str(main.edges)},
            warnings=warnings,
            parser=f"geometry-service/{result.service_version}",
        ),
    )
