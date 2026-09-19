"""`engineering_advice` job (T-118, F-005): measure the part, then let the engineer answer.

The worker measures walls, mass and slenderness in its sandbox; the API adds the holes
from the operation log; the assistant turns both into a verdict. A fix is only offered
when it builds into a valid plan for this very version.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from worker import engineering as measuring

from app.api.errors import ValidationFailedError
from app.engineering import assistant, knowledge
from app.jobs.print_jobs import _mesh_as_stl
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.engineering import EngineeringReportRecord
from app.models.printing import Material
from app.models.versioning import Asset, ProjectVersion
from app.services import ai_commands, edits, engineering


def _validated_fix(
    ctx: JobContext, version: ProjectVersion, fix: assistant.Fix | None
) -> assistant.Fix | None:
    """Keep a fix only if the edit endpoint would accept it as it is."""
    if fix is None:
        return None
    try:
        edits.build_plan(ctx.db, version=version, operations=fix.operations, label=fix.label)
    except ValidationFailedError:
        return None
    return fix


@register(engineering.ENGINEERING_JOB)
def handle_engineering_advice(ctx: JobContext) -> dict[str, Any]:
    version_id = uuid.UUID(str(ctx.job.input["version_id"]))
    asset_id = uuid.UUID(str(ctx.job.input["asset_id"]))
    version = ctx.db.get(ProjectVersion, version_id)
    asset = ctx.db.get(Asset, asset_id)
    if version is None or asset is None:
        raise JobFailureError("input_missing", "version or asset no longer exists")

    question: str | None = ctx.job.input.get("question")
    purpose: str | None = ctx.job.input.get("purpose")
    material_id: str | None = ctx.job.input.get("material_id")
    selection: dict[str, Any] | None = ctx.job.input.get("region")
    region = selection.get("region") if selection else None

    text = " ".join(part for part in (question, purpose) if part)
    load = assistant.load_of(text)
    limit = knowledge.recommended_wall_mm(material_id, load)
    densities = {
        row.id: float(row.density_g_cm3)
        for row in ctx.db.scalars(sa.select(Material))
        if row.id in knowledge.MATERIALS
    }

    with tempfile.TemporaryDirectory(prefix="engineering-") as tmp_dir:
        tmp = Path(tmp_dir)
        mesh_path = _mesh_as_stl(ctx, asset, tmp)
        ctx.progress(20, "downloaded")
        request = measuring.FactsRequest.model_validate(
            {"limit_mm": limit, "region": region, "densities_g_cm3": densities}
        )
        measured = measuring.run_in_sandbox(mesh_path, "stl", request)
    if not measured.ok:
        raise JobFailureError(
            "measurement_failed", measured.message or "the model could not be measured"
        )
    ctx.progress(70, "measured")

    operations = ai_commands.current_operations(ctx.db, version.id)
    undersize = ctx.job.input.get("hole_undersize_mm")
    report = assistant.build_report(
        facts=assistant.Facts.model_validate(measured.model_dump(mode="json")),
        operations=operations,
        material_id=material_id,
        question=question,
        purpose=purpose,
        region=region,
        undersize_mm=float(undersize) if undersize is not None else None,
    )
    if report.answer is not None:
        report.answer.fix = _validated_fix(ctx, version, report.answer.fix)
    for recommendation in report.recommendations:
        recommendation.fix = _validated_fix(ctx, version, recommendation.fix)

    payload = report.model_dump(mode="json")
    record = EngineeringReportRecord(
        workspace_id=ctx.job.workspace_id,
        project_version_id=version.id,
        job_id=ctx.job.id,
        material_id=material_id if material_id in densities else None,
        question=question,
        region=selection,
        report=payload,
    )
    ctx.db.add(record)
    ctx.db.flush()
    ctx.progress(100, "done")
    return {"report_id": str(record.id), "version_id": str(version.id), "report": payload}
