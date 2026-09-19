"""Cut a model into printable parts (T-142, F-081)."""

import uuid
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.schemas import JobAccepted
from app.services import splitting

router = APIRouter(tags=["splitting"])

Axis = Literal["x", "y", "z"]


class CutPlaneBody(BaseModel):
    """On an axis at a coordinate or a fraction of the extent, or anywhere by point + normal."""

    axis: Axis | None = None
    offset_mm: float | None = None
    fraction: float | None = Field(default=None, gt=0.0, lt=1.0)
    point_mm: list[float] | None = Field(default=None, min_length=3, max_length=3)
    normal: list[float] | None = Field(default=None, min_length=3, max_length=3)


class ConnectorsBody(BaseModel):
    kind: Literal["none", "dowel"] = "dowel"
    diameter_mm: float = Field(default=5.0, ge=1.5, le=20.0)
    length_mm: float = Field(default=12.0, ge=4.0, le=60.0)
    clearance_mm: float = Field(default=0.25, ge=0.0, le=1.0)


class SplitBody(BaseModel):
    planes: list[CutPlaneBody] = Field(default_factory=list, max_length=8)
    # N equal parts along an axis (the longest extent when unset)
    parts: int | None = Field(default=None, ge=2, le=12)
    axis: Axis | None = None
    # cut until every part fits the printer's bed (the named profile, else the default)
    fit_bed: bool = False
    printer_profile_id: uuid.UUID | None = None
    margin_mm: float = Field(default=5.0, ge=0.0, le=50.0)
    connectors: ConnectorsBody = Field(default_factory=ConnectorsBody)
    gap_mm: float = Field(default=8.0, ge=0.0, le=50.0)
    # close holes and fix normals first when the mesh is not a closed volume
    repair: bool = True
    label: str | None = Field(default=None, max_length=200)
    # T-052: keep the parts as a draft until the user accepts them
    preview: bool = False


@router.post(
    "/models/{version_id}/split", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted
)
def split_model(
    version_id: uuid.UUID,
    body: SplitBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    request = body.model_dump(
        mode="json",
        exclude={"fit_bed", "printer_profile_id", "label", "preview"},
        exclude_none=True,
    )
    request["planes"] = [plane.model_dump(mode="json", exclude_none=True) for plane in body.planes]
    job = splitting.enqueue_split(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        request=request,
        fit_bed=body.fit_bed,
        printer_profile_id=body.printer_profile_id,
        label=body.label,
        preview=body.preview,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
