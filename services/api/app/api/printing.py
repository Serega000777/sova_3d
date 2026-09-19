"""Printing endpoints: catalogue, printer profiles (T-070), analyze/optimize print (T-064/T-067)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.models.printing import AnalysisKind, Technology
from app.services import calibration, printing

router = APIRouter(tags=["printing"])


class PrinterModelOut(BaseModel):
    id: str
    vendor: str
    model: str
    technology: Technology
    bed_x_mm: Decimal
    bed_y_mm: Decimal
    bed_z_mm: Decimal
    nozzle_mm: Decimal
    max_overhang_deg: Decimal
    print_speed_mm_s: Decimal

    model_config = {"from_attributes": True}


class MaterialOut(BaseModel):
    id: str
    name: str
    kind: str
    density_g_cm3: Decimal
    price_per_kg: Decimal
    currency: str
    shrinkage_pct: Decimal
    min_wall_mm: Decimal | None
    notes: str | None

    model_config = {"from_attributes": True}


class ProfileOverrides(BaseModel):
    nozzle_mm: Decimal | None = Field(default=None, gt=0, le=2)
    layer_height_mm: Decimal | None = Field(default=None, gt=0, le=1)
    max_overhang_deg: Decimal | None = Field(default=None, gt=0, lt=90)
    print_speed_mm_s: Decimal | None = Field(default=None, gt=0, le=1000)
    default_material_id: str | None = None
    calibration: dict[str, Any] | None = None
    is_default: bool | None = None


class ProfileCreate(ProfileOverrides):
    workspace_id: uuid.UUID
    printer_model_id: str
    name: str = Field(min_length=1, max_length=100)


class ProfileUpdate(ProfileOverrides):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    printer_model_id: str | None = None


class ProfileOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    printer_model_id: str
    name: str
    nozzle_mm: Decimal | None
    layer_height_mm: Decimal
    max_overhang_deg: Decimal | None
    print_speed_mm_s: Decimal | None
    default_material_id: str | None
    calibration: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnalyzeBody(BaseModel):
    printer_profile_id: uuid.UUID | None = None
    material_id: str | None = None


class OptimizeBody(AnalyzeBody):
    apply: bool = False


class AnalysisOut(BaseModel):
    id: uuid.UUID
    project_version_id: uuid.UUID
    kind: AnalysisKind
    score: Decimal
    status: str
    printer_profile_id: uuid.UUID | None
    material_id: str | None
    result_version_id: uuid.UUID | None
    report: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/printer-models", response_model=list[PrinterModelOut])
def list_printer_models(db: DbDep, principal: PrincipalDep) -> list[PrinterModelOut]:
    return [PrinterModelOut.model_validate(m) for m in printing.list_printer_models(db)]


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(db: DbDep, principal: PrincipalDep) -> list[MaterialOut]:
    return [MaterialOut.model_validate(m) for m in printing.list_materials(db)]


@router.post("/printer-profiles", status_code=status.HTTP_201_CREATED, response_model=ProfileOut)
def create_profile(body: ProfileCreate, db: DbDep, principal: PrincipalDep) -> ProfileOut:
    overrides = body.model_dump(
        exclude={"workspace_id", "printer_model_id", "name"}, exclude_none=True
    )
    profile = printing.create_profile(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        printer_model_id=body.printer_model_id,
        name=body.name,
        overrides=overrides,
    )
    return ProfileOut.model_validate(profile)


@router.get("/printer-profiles", response_model=list[ProfileOut])
def list_profiles(workspace_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[ProfileOut]:
    rows = printing.list_profiles(db, user_id=principal.user_id, workspace_id=workspace_id)
    return [ProfileOut.model_validate(p) for p in rows]


@router.get("/printer-profiles/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ProfileOut:
    return ProfileOut.model_validate(
        printing.get_profile(db, user_id=principal.user_id, profile_id=profile_id)
    )


@router.put("/printer-profiles/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: uuid.UUID, body: ProfileUpdate, db: DbDep, principal: PrincipalDep
) -> ProfileOut:
    changes = body.model_dump(exclude_none=True)
    profile = printing.update_profile(
        db, user_id=principal.user_id, profile_id=profile_id, changes=changes
    )
    return ProfileOut.model_validate(profile)


@router.delete("/printer-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    printing.delete_profile(db, user_id=principal.user_id, profile_id=profile_id)


@router.post(
    "/models/{version_id}/analyze-print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def analyze_print(
    version_id: uuid.UUID,
    body: AnalyzeBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = printing.enqueue_analysis(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        kind=AnalysisKind.analysis,
        printer_profile_id=body.printer_profile_id,
        material_id=body.material_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/optimize-print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def optimize_print(
    version_id: uuid.UUID,
    body: OptimizeBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    job = printing.enqueue_analysis(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        kind=AnalysisKind.optimize,
        printer_profile_id=body.printer_profile_id,
        material_id=body.material_id,
        apply=body.apply,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


# --- per-printer calibration (F-028/F-029) ---------------------------------------------------


class CalibrationPrintOut(BaseModel):
    profile_id: uuid.UUID
    project_id: uuid.UUID
    job: JobAccepted
    features: list[dict[str, Any]]


@router.get("/printer-profiles/{profile_id}/calibration-coupon")
def calibration_coupon(profile_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> dict[str, Any]:
    """What the coupon contains and what to measure on it."""
    printing.get_profile(db, user_id=principal.user_id, profile_id=profile_id)
    return {"features": calibration.coupon_features(), "plan": calibration.coupon_plan()}


@router.post(
    "/printer-profiles/{profile_id}/calibration-print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CalibrationPrintOut,
)
def start_calibration_print(
    profile_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> CalibrationPrintOut:
    """A project with the coupon being built for this printer."""
    profile, project, job = calibration.start_calibration_print(
        db, user_id=principal.user_id, profile_id=profile_id
    )
    return CalibrationPrintOut(
        profile_id=profile.id,
        project_id=project.id,
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
        features=calibration.coupon_features(),
    )


@router.post("/printer-profiles/{profile_id}/calibration", response_model=ProfileOut)
def record_calibration(
    profile_id: uuid.UUID,
    body: calibration.Measurements,
    db: DbDep,
    principal: PrincipalDep,
) -> ProfileOut:
    """Caliper readings from the printed coupon become the profile's calibration."""
    profile = calibration.record_measurements(
        db, user_id=principal.user_id, profile_id=profile_id, measurements=body
    )
    return ProfileOut.model_validate(profile)


@router.get("/models/{version_id}/print-analyses", response_model=list[AnalysisOut])
def list_print_analyses(
    version_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[AnalysisOut]:
    rows = printing.list_analyses(db, user_id=principal.user_id, version_id=version_id)
    return [AnalysisOut.model_validate(r) for r in rows]


@router.get("/print-analyses/{analysis_id}", response_model=AnalysisOut)
def get_print_analysis(analysis_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> AnalysisOut:
    return AnalysisOut.model_validate(
        printing.get_analysis(db, user_id=principal.user_id, analysis_id=analysis_id)
    )
