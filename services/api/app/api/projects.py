"""Projects (T-014) and versions (T-015) endpoints under /api/v1."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.models.core import Units
from app.models.versioning import AssetRole, VersionState
from app.services import projects

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ProjectOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    units: Units
    head_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VersionCreate(BaseModel):
    parent_version_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)
    assets: dict[AssetRole, uuid.UUID] = Field(default_factory=dict)
    finalize: bool = True


class VersionAssetOut(BaseModel):
    asset_id: uuid.UUID
    role: AssetRole

    model_config = {"from_attributes": True}


class VersionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    sequence_no: int
    state: VersionState
    label: str | None
    provenance: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime
    finalized_at: datetime | None
    assets: list[VersionAssetOut]

    model_config = {"from_attributes": True}


class ProjectSummary(ProjectOut):
    head_version: VersionOut | None


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
def create_project(body: ProjectCreate, db: DbDep, principal: PrincipalDep) -> ProjectOut:
    project = projects.create_project(
        db,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        name=body.name,
        description=body.description,
    )
    return ProjectOut.model_validate(project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: DbDep,
    principal: PrincipalDep,
    workspace_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectOut]:
    rows = projects.list_projects(
        db, user_id=principal.user_id, workspace_id=workspace_id, limit=limit, offset=offset
    )
    return [ProjectOut.model_validate(p) for p in rows]


@router.get("/projects/{project_id}", response_model=ProjectSummary)
def get_project(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ProjectSummary:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    head = (
        projects.get_version(db, user_id=principal.user_id, version_id=project.head_version_id)
        if project.head_version_id
        else None
    )
    return ProjectSummary(
        **ProjectOut.model_validate(project).model_dump(),
        head_version=VersionOut.model_validate(head) if head else None,
    )


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, db: DbDep, principal: PrincipalDep
) -> ProjectOut:
    project = projects.update_project(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        name=body.name,
        description=body.description,
    )
    return ProjectOut.model_validate(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    projects.delete_project(db, user_id=principal.user_id, project_id=project_id)


@router.get("/projects/{project_id}/versions", response_model=list[VersionOut])
def list_versions(
    project_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[VersionOut]:
    rows = projects.list_versions(
        db, user_id=principal.user_id, project_id=project_id, limit=limit, offset=offset
    )
    return [VersionOut.model_validate(v) for v in rows]


@router.post(
    "/projects/{project_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionOut,
)
def create_version(
    project_id: uuid.UUID, body: VersionCreate, db: DbDep, principal: PrincipalDep
) -> VersionOut:
    version = projects.create_version(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        parent_version_id=body.parent_version_id,
        label=body.label,
        provenance=body.provenance,
        assets=body.assets,
        finalize=body.finalize,
    )
    return VersionOut.model_validate(version)


@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> VersionOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    return VersionOut.model_validate(version)


@router.get("/versions/{version_id}/lineage", response_model=list[VersionOut])
def get_lineage(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[VersionOut]:
    chain = projects.lineage(db, user_id=principal.user_id, version_id=version_id)
    return [VersionOut.model_validate(v) for v in chain]


@router.post(
    "/versions/{version_id}/finalize",
    response_model=VersionOut,
)
def finalize_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> VersionOut:
    version = projects.finalize_version_as(db, user_id=principal.user_id, version_id=version_id)
    return VersionOut.model_validate(version)
