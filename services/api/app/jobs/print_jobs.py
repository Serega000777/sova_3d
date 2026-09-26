"""`analyze_print` (T-064) and `optimize_print` (T-067) job handlers."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import gcode as slicer
from worker import printcheck, slicing

from app import formats
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.core import Units
from app.models.execution import JobArtifact
from app.models.printing import AnalysisKind, Material, PrintAnalysisRecord, PrinterProfile
from app.models.versioning import Asset, AssetKind, AssetRole, ProjectVersion, VersionAsset
from app.services import print_diagnosis, printing, projects
from app.storage import ObjectNotFoundError


def _download(ctx: JobContext, asset: Asset, target: Path) -> None:
    try:
        with target.open("wb") as handle:
            for chunk in ctx.storage.iter_chunks(asset.storage_key):
                handle.write(chunk)
    except ObjectNotFoundError as exc:
        raise JobFailureError("asset_missing", str(exc), retryable=True) from exc


def _mesh_as_stl(ctx: JobContext, asset: Asset, tmp: Path) -> Path:
    """Analysis reads binary STL; other mesh formats go through the validated exporter."""
    source = tmp / f"source.{asset.format}"
    _download(ctx, asset, source)
    if asset.format == "stl":
        return source
    from worker import exporters

    target = tmp / "source.stl"
    outcome = exporters.export_mesh(source, asset.format or "stl", "stl", target)
    if not outcome.ok:
        error = outcome.error
        raise JobFailureError(
            error.code if error else "convert_failed",
            error.message if error else "could not convert the model to STL",
        )
    return target


def _run(ctx: JobContext, *, optimize: bool) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    asset = ctx.db.get(Asset, asset_id)
    if version is None or asset is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")
    profile_id = ctx.job.input.get("printer_profile_id")
    material_id = ctx.job.input.get("material_id")
    profile = ctx.db.get(PrinterProfile, uuid.UUID(profile_id)) if profile_id else None
    material = ctx.db.get(Material, material_id) if material_id else None
    printer_cfg = printcheck.PrinterProfile.model_validate(
        printing.printer_settings(ctx.db, profile)
    )
    material_cfg = printcheck.MaterialProfile.model_validate(printing.material_settings(material))
    apply = bool(ctx.job.input.get("apply")) and optimize

    with tempfile.TemporaryDirectory(prefix="printcheck-") as tmp_dir:
        tmp = Path(tmp_dir)
        mesh_path = _mesh_as_stl(ctx, asset, tmp)
        ctx.progress(20, "downloaded")
        rotated_path = tmp / "rotated.stl" if apply else None
        outcome = printcheck.analyze_file(
            mesh_path,
            printer=printer_cfg,
            material=material_cfg,
            optimize=optimize,
            apply_to=rotated_path,
        )
        if not outcome.ok or outcome.analysis is None:
            error = outcome.error or {}
            raise JobFailureError(
                error.get("code", "analysis_failed"),
                "the print analysis could not be completed",
                details={"detail": error.get("message")},
            )
        analysis = outcome.analysis
        ctx.progress(80, "analyzed")
        rotated_bytes = (
            rotated_path.read_bytes() if rotated_path and rotated_path.exists() else None
        )

    record = PrintAnalysisRecord(
        workspace_id=ctx.job.workspace_id,
        project_version_id=version.id,
        asset_id=asset.id,
        job_id=ctx.job.id,
        printer_profile_id=profile.id if profile else None,
        material_id=material.id if material else None,
        kind=AnalysisKind.optimize if optimize else AnalysisKind.analysis,
        score=analysis.score.total,
        status=analysis.score.status,
        report=analysis.model_dump(mode="json"),
    )
    ctx.db.add(record)
    ctx.db.flush()

    result: dict[str, Any] = {
        "analysis_id": str(record.id),
        "kind": record.kind.value,
        "score": analysis.score.total,
        "status": analysis.score.status,
        "summary": analysis.summary,
        "report": record.report,
    }
    if optimize and analysis.recommended is not None:
        result["recommended_orientation"] = analysis.recommended.orientation.model_dump()
        result["applied"] = False

    if rotated_bytes is not None and analysis.recommended is not None:
        new_asset = _store_stl(ctx, asset, rotated_bytes, analysis.recommended.orientation.label)
        orientation = analysis.recommended.orientation
        new_version = projects.create_version_internal(
            ctx.db,
            project_id=version.project_id,
            parent_version_id=version.id,
            label=f"Print orientation: {orientation.label}",
            provenance={
                "job_id": str(ctx.job.id),
                "source_version_id": str(version.id),
                "operation": "optimize_print",
                "print_analysis_id": str(record.id),
                "orientation": orientation.model_dump(),
            },
            assets={AssetRole.model: new_asset.id},
            created_by=ctx.job.created_by,
        )
        ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=new_asset.id, role="model"))
        record.result_version_id = new_version.id
        ctx.db.flush()
        result["applied"] = True
        result["version_id"] = str(new_version.id)
        result["asset_id"] = str(new_asset.id)

    ctx.progress(100, "done")
    return result


def _store_stl(ctx: JobContext, source: Asset, data: bytes, label: str) -> Asset:
    sha256 = hashlib.sha256(data).hexdigest()
    existing = ctx.db.scalar(
        sa.select(Asset).where(Asset.workspace_id == source.workspace_id, Asset.sha256 == sha256)
    )
    if existing is not None:
        return existing
    spec = formats.FORMATS["stl"]
    key = ctx.storage.object_key(source.workspace_id, sha256, "stl")
    ctx.storage.put(key, data, spec.mime_types[0])
    asset = Asset(
        workspace_id=source.workspace_id,
        kind=AssetKind.derived,
        sha256=sha256,
        storage_key=key,
        mime=spec.mime_types[0],
        format="stl",
        byte_size=len(data),
        units=Units.mm,
        metadata_={
            "derived_from": str(source.id),
            "operation": "optimize_print",
            "orientation": label,
            "job_id": str(ctx.job.id),
        },
        created_by=ctx.job.created_by,
    )
    ctx.db.add(asset)
    ctx.db.flush()
    return asset


@register(printing.ANALYZE_JOB)
def handle_analyze_print(ctx: JobContext) -> dict[str, Any]:
    return _run(ctx, optimize=False)


@register(printing.OPTIMIZE_JOB)
def handle_optimize_print(ctx: JobContext) -> dict[str, Any]:
    return _run(ctx, optimize=True)


@register("slice_preview")
def handle_slice_preview(ctx: JobContext) -> dict[str, Any]:
    asset = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["asset_id"])))
    if asset is None:
        raise JobFailureError("input_missing", "model asset no longer exists")
    profile_id = ctx.job.input.get("printer_profile_id")
    profile = ctx.db.get(PrinterProfile, uuid.UUID(profile_id)) if profile_id else None
    printer = printcheck.PrinterProfile.model_validate(printing.printer_settings(ctx.db, profile))
    with tempfile.TemporaryDirectory(prefix="slice-preview-") as tmp_dir:
        mesh_path = _mesh_as_stl(ctx, asset, Path(tmp_dir))
        ctx.progress(25, "downloaded")
        try:
            result = slicing.preview_file(mesh_path, printer)
        except ValueError as exc:
            raise JobFailureError("slice_preview_failed", str(exc)) from exc
    ctx.progress(100, "previewed")
    return result


@register(printing.SLICE_JOB)
def handle_slice(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    source = ctx.db.get(Asset, uuid.UUID(str(ctx.job.input["asset_id"])))
    if version is None or source is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")
    profile_id = ctx.job.input.get("printer_profile_id")
    profile = ctx.db.get(PrinterProfile, uuid.UUID(profile_id)) if profile_id else None
    printer = printcheck.PrinterProfile.model_validate(printing.printer_settings(ctx.db, profile))
    material_id = str(ctx.job.input.get("material_id") or "pla")
    settings = slicer.SliceSettings(
        material_id=material_id,
        infill_density_pct=float(ctx.job.input.get("infill_density_pct", 20.0)),
        infill_pattern=str(ctx.job.input.get("infill_pattern") or "lines"),
        wall_count=int(ctx.job.input.get("wall_count", 2)),
        supports=bool(ctx.job.input.get("supports", False)),
        skirt=bool(ctx.job.input.get("skirt", True)),
        # F-056: what earlier print reports taught, read when the job runs, like calibration
        tuning=slicer.PrintTuning(**print_diagnosis.tuning_of(profile, material_id)),
    )
    with tempfile.TemporaryDirectory(prefix="slice-") as tmp_dir:
        tmp = Path(tmp_dir)
        mesh_path = _mesh_as_stl(ctx, source, tmp)
        ctx.progress(20, "downloaded")
        try:
            stats = slicer.slice_file_in_sandbox(mesh_path, printer, settings, tmp / "out")
        except ValueError as exc:
            raise JobFailureError("slice_failed", str(exc)) from exc
        ctx.progress(80, "sliced")
        data = (tmp / "out" / str(stats["gcode_file"])).read_bytes()

    spec = formats.FORMATS["gcode"]
    sha256 = str(stats["gcode_sha256"])
    asset = ctx.db.scalar(
        sa.select(Asset).where(Asset.workspace_id == source.workspace_id, Asset.sha256 == sha256)
    )
    if asset is None:
        key = ctx.storage.object_key(source.workspace_id, sha256, spec.extensions[0])
        ctx.storage.put(key, data, spec.mime_types[0])
        asset = Asset(
            workspace_id=source.workspace_id,
            kind=AssetKind.derived,
            sha256=sha256,
            storage_key=key,
            mime=spec.mime_types[0],
            format="gcode",
            byte_size=len(data),
            units=Units.mm,
            metadata_={
                "derived_from": str(source.id),
                "operation": "slice",
                "printer_profile_id": str(profile.id) if profile else None,
                "settings": settings.model_dump(),
                "stats": stats,
                "job_id": str(ctx.job.id),
            },
            created_by=ctx.job.created_by,
        )
        ctx.db.add(asset)
        ctx.db.flush()
    if ctx.db.get(VersionAsset, (version.id, asset.id, AssetRole.export)) is None:
        ctx.db.add(VersionAsset(version_id=version.id, asset_id=asset.id, role=AssetRole.export))
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role="export"))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "asset_id": str(asset.id),
        "format": "gcode",
        "byte_size": len(data),
        "stats": stats,
        "material_id": material_id,
        "printer_profile_id": profile_id,
    }
