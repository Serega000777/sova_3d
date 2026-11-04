"""Reference 81: reusable exact S/M/L families over immutable preview versions."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.services import size_families

router = APIRouter(tags=["size-families"])
SizeLabel = Literal["S", "M", "L"]


class SizeFamilyMemberBody(BaseModel):
    label: SizeLabel
    version_id: uuid.UUID


class SizeFamilyCreate(BaseModel):
    source_version_id: uuid.UUID
    selected_label: SizeLabel = "M"
    members: list[SizeFamilyMemberBody] = Field(min_length=3, max_length=3)


class SizeFamilySelect(BaseModel):
    label: SizeLabel


class SizeFamilyMemberOut(BaseModel):
    label: SizeLabel
    version_id: uuid.UUID
    width_mm: float
    depth_mm: float
    height_mm: float


class SizeFamilyOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_version_id: uuid.UUID
    selected_label: SizeLabel | None
    members: list[SizeFamilyMemberOut]
    created_at: datetime


def _out(record: size_families.SizeFamilyRecord) -> SizeFamilyOut:
    return SizeFamilyOut(
        id=record.id,
        project_id=record.project_id,
        source_version_id=record.source_version_id,
        selected_label=record.selected_label,
        members=[
            SizeFamilyMemberOut(
                label=member.label,
                version_id=member.version_id,
                width_mm=member.width_mm,
                depth_mm=member.depth_mm,
                height_mm=member.height_mm,
            )
            for member in record.members
        ],
        created_at=record.created_at,
    )


@router.get("/projects/{project_id}/size-families", response_model=list[SizeFamilyOut])
def list_size_families(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[SizeFamilyOut]:
    return [
        _out(record)
        for record in size_families.list_size_families(
            db, user_id=principal.user_id, project_id=project_id
        )
    ]


@router.post(
    "/projects/{project_id}/size-families",
    response_model=SizeFamilyOut,
    status_code=status.HTTP_201_CREATED,
)
def create_size_family(
    project_id: uuid.UUID,
    body: SizeFamilyCreate,
    db: DbDep,
    principal: PrincipalDep,
) -> SizeFamilyOut:
    member_ids = {member.label: member.version_id for member in body.members}
    return _out(
        size_families.create_size_family(
            db,
            user_id=principal.user_id,
            project_id=project_id,
            source_version_id=body.source_version_id,
            member_ids=member_ids,
            selected_label=body.selected_label,
        )
    )


@router.post(
    "/projects/{project_id}/size-families/{family_id}/select",
    response_model=SizeFamilyOut,
)
def select_size_family_member(
    project_id: uuid.UUID,
    family_id: uuid.UUID,
    body: SizeFamilySelect,
    db: DbDep,
    principal: PrincipalDep,
) -> SizeFamilyOut:
    return _out(
        size_families.select_size_family_member(
            db,
            user_id=principal.user_id,
            project_id=project_id,
            family_id=family_id,
            label=body.label,
        )
    )
