"""Job handlers. Importing this module registers them with the runner."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import repair as mesh_repair

import app.jobs.ai_command  # noqa: F401 — registers `ai_command`
import app.jobs.assembly_inspection  # noqa: F401 — registers `inspect_assembly_geometry`
import app.jobs.blender_handoff  # noqa: F401 — registers `blender_handoff`
import app.jobs.demo_scan  # noqa: F401 — registers `demo_scan`
import app.jobs.diagnose_print  # noqa: F401 — registers `diagnose_print_photo`
import app.jobs.enclosure  # noqa: F401 — registers `build_enclosure`
import app.jobs.engineering_advice  # noqa: F401 — registers `engineering_advice`
import app.jobs.execute_plan  # noqa: F401 — registers `execute_plan`
import app.jobs.export_job  # noqa: F401 — registers `export`
import app.jobs.facade  # noqa: F401 — registers `edit_facade`
import app.jobs.fit_test  # noqa: F401 — registers `fit_test`
import app.jobs.furniture  # noqa: F401 — registers `place_furniture`
import app.jobs.generate_mesh  # noqa: F401 — registers `generate_mesh`
import app.jobs.house_box  # noqa: F401 — registers `build_house_box`
import app.jobs.house_walls  # noqa: F401 — registers `build_house_walls`
import app.jobs.import_model  # noqa: F401 — registers `import_model` / `convert_asset`
import app.jobs.manual_edit  # noqa: F401 — registers `manual_edit`
import app.jobs.mechanism  # noqa: F401 — registers `build_hinged_lid`, `build_sliding_lid`
import app.jobs.mesh_edit  # noqa: F401 — registers `mesh_edit`
import app.jobs.metrology  # noqa: F401 — registers `physical_compare`
import app.jobs.paint_model  # noqa: F401 — registers `paint_model`
import app.jobs.print_jobs  # noqa: F401 — registers `analyze_print` / `optimize_print`
import app.jobs.reconstruct_scan  # noqa: F401 — registers `reconstruct_scan`
import app.jobs.reverse_engineering  # noqa: F401 — registers `reverse_engineer`
import app.jobs.rollback  # noqa: F401 — registers `rollback`
import app.jobs.site_plan  # noqa: F401 — registers `compose_site_plan`
import app.jobs.split_model  # noqa: F401 — registers `split_model`
import app.jobs.thumbnail  # noqa: F401 — registers `render_thumbnail`
import app.jobs.turntable_video  # noqa: F401 — registers `render_turntable_video`
import app.jobs.video_frames  # noqa: F401 — registers `extract_video_frames`
from app import formats
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.execution import JobArtifact
from app.models.versioning import Asset, AssetKind, AssetRole, ProjectVersion
from app.services import projects
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of
from app.services.content_addressed_assets import lock_content_addressed_assets
from app.storage import ObjectNotFoundError


@register("remove_fragments")
@register("repair")
def handle_repair(ctx: JobContext) -> dict[str, Any]:
    """F-006: repair the version's mesh into a new derived asset + child version."""
    operation = "remove_fragments" if ctx.job.type == "remove_fragments" else "repair"
    fragment_max_size_mm: float | None = None
    selected_steps: tuple[mesh_repair.RepairStep, ...] | None = None
    target_defect_ids: tuple[str, ...] | None = None
    raw_defect_ids = ctx.job.input.get("defect_ids")
    if raw_defect_ids is not None:
        if (
            not isinstance(raw_defect_ids, list)
            or not raw_defect_ids
            or any(not isinstance(defect_id, str) for defect_id in raw_defect_ids)
            or len(set(raw_defect_ids)) != len(raw_defect_ids)
        ):
            raise JobFailureError("invalid_defect_ids", "selected defect ids are invalid")
        target_defect_ids = tuple(raw_defect_ids)
    if operation == "remove_fragments":
        raw_threshold = ctx.job.input.get("max_size_mm")
        if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, int | float):
            raise JobFailureError("invalid_fragment_size", "fragment size must be a number in mm")
        fragment_max_size_mm = float(raw_threshold)
    else:
        raw_steps = ctx.job.input.get("steps")
        if raw_steps is not None:
            allowed = {"degenerate", "normals", "holes"}
            if (
                not isinstance(raw_steps, list)
                or not raw_steps
                or any(not isinstance(step, str) or step not in allowed for step in raw_steps)
            ):
                raise JobFailureError("invalid_repair_steps", "repair steps are invalid")
            selected_steps = tuple(dict.fromkeys(raw_steps))
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    if version is None:
        raise JobFailureError("version_not_found", str(version_id))
    source_asset = model_asset_of(ctx.db, version)
    if source_asset is None or source_asset.format not in REPAIRABLE_FORMATS:
        raise JobFailureError("no_repairable_asset", "version has no mesh asset to repair")

    with tempfile.TemporaryDirectory(prefix="repair-") as tmp:
        source_path = Path(tmp) / f"source.{source_asset.format}"
        try:
            with source_path.open("wb") as handle:
                for chunk in ctx.storage.iter_chunks(source_asset.storage_key):
                    handle.write(chunk)
        except ObjectNotFoundError as exc:
            raise JobFailureError("asset_missing", str(exc), retryable=True) from exc
        ctx.progress(15, "downloaded")

        output_path = Path(tmp) / "repaired.stl"
        outcome = mesh_repair.repair_in_sandbox(
            source_path,
            source_asset.format,
            output_path,
            fragment_max_size_mm=fragment_max_size_mm,
            steps=selected_steps,
            target_defect_ids=target_defect_ids,
        )
        if not outcome.ok or outcome.report is None:
            error = outcome.error
            raise JobFailureError(
                error.code if error else "repair_failed",
                error.message if error else "repair produced no output",
                details={"source_asset_id": str(source_asset.id)},
            )
        ctx.progress(70, "repaired")
        repaired_bytes = output_path.read_bytes()

    report = outcome.report.model_dump(mode="json")
    sha256 = hashlib.sha256(repaired_bytes).hexdigest()
    spec = formats.FORMATS["stl"]
    lock_content_addressed_assets(ctx.db, workspace_id=source_asset.workspace_id, sha256s=(sha256,))
    asset = ctx.db.scalar(
        sa.select(Asset).where(
            Asset.workspace_id == source_asset.workspace_id, Asset.sha256 == sha256
        )
    )
    if asset is None:
        key = ctx.storage.object_key(source_asset.workspace_id, sha256, "stl")
        ctx.storage.put(key, repaired_bytes, spec.mime_types[0])
        asset = Asset(
            workspace_id=source_asset.workspace_id,
            kind=AssetKind.derived,
            sha256=sha256,
            storage_key=key,
            mime=spec.mime_types[0],
            format="stl",
            byte_size=len(repaired_bytes),
            units=source_asset.units,
            metadata_={
                "derived_from": str(source_asset.id),
                "operation": operation,
                "job_id": str(ctx.job.id),
            },
            created_by=ctx.job.created_by,
        )
        ctx.db.add(asset)
        ctx.db.flush()
    ctx.progress(85, "uploaded")

    new_version = projects.create_version_internal(
        ctx.db,
        project_id=version.project_id,
        parent_version_id=version.id,
        label="Remove fragments" if operation == "remove_fragments" else "Repair",
        provenance={
            "job_id": str(ctx.job.id),
            "source_version_id": str(version.id),
            "operation": operation,
            "repair_report": report,
        },
        assets={AssetRole.model: asset.id},
        created_by=ctx.job.created_by,
    )
    ctx.db.add(JobArtifact(job_id=ctx.job.id, asset_id=asset.id, role=AssetRole.model.value))
    ctx.db.flush()
    ctx.progress(100, "done")
    return {
        "version_id": str(new_version.id),
        "asset_id": str(asset.id),
        "source_version_id": str(version.id),
        "report": report,
    }
