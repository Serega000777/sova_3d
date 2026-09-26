"""`diagnose_print_photo` job (F-056): symptoms seen in photos join the person's report."""

from __future__ import annotations

import uuid
from typing import Any

from app.ai import print_vision
from app.ai.contract import Photo
from app.config import load_settings
from app.jobs.runner import JobContext, JobFailureError, register
from app.models.printing import PrinterProfile
from app.models.usage import UsageKind
from app.models.versioning import Asset
from app.services import print_diagnosis, usage
from app.storage import ObjectNotFoundError


@register(print_diagnosis.DIAGNOSE_PHOTO_JOB)
def handle_diagnose_print_photo(ctx: JobContext) -> dict[str, Any]:
    profile = ctx.db.get(PrinterProfile, uuid.UUID(str(ctx.job.input["printer_profile_id"])))
    if profile is None:
        raise JobFailureError("printer_profile_not_found", "the printer profile is gone")
    report = print_diagnosis.PrintReport.model_validate(ctx.job.input["report"])
    photos: list[Photo] = []
    for entry in ctx.job.input.get("photos", []):
        asset = ctx.db.get(Asset, uuid.UUID(str(entry["asset_id"])))
        if asset is None:
            raise JobFailureError("photo_missing", "a photo was deleted before it was read")
        try:
            data = ctx.storage.get(asset.storage_key)
        except ObjectNotFoundError as exc:
            raise JobFailureError("photo_missing", str(exc), retryable=True) from exc
        photos.append(Photo(asset_id=str(asset.id), media_type=entry["media_type"], data=data))
    ctx.progress(20, "looking at the photos")

    settings = load_settings()
    findings, spent = print_vision.identify(
        photos,
        report.material_id,
        client=print_vision.client_for(settings),
        model=settings.ai_model,
    )
    usage.record(
        ctx.db,
        workspace_id=profile.workspace_id,
        kind=UsageKind.ai_tokens,
        quantity=spent.input_tokens + spent.output_tokens,
        unit="token",
        cost_usd=spent.cost_usd,
        credits_delta=-spent.cost_usd,
        user_id=ctx.job.created_by,
        job_id=ctx.job.id,
        metadata={
            "provider": spent.provider,
            "model": spent.model,
            "operation": print_diagnosis.DIAGNOSE_PHOTO_JOB,
            "input_tokens": spent.input_tokens,
            "output_tokens": spent.output_tokens,
        },
    )
    seen = findings.confident()
    combined = report.model_copy(
        update={"symptoms": list(dict.fromkeys([*report.symptoms, *seen]))}
    )
    diagnosis = print_diagnosis.apply_report(ctx.db, profile, combined, seen_in_photos=list(seen))
    ctx.progress(100, "diagnosed")
    return {
        **diagnosis.model_dump(mode="json"),
        "photo": findings.model_dump(mode="json"),
        "cost_usd": str(spent.cost_usd),
    }
