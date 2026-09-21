"""Projects (T-014) and versions (T-015) endpoints under /api/v1."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, StorageDep
from app.api.errors import NotFoundError, ValidationFailedError
from app.models.core import Units, WorkspaceRole
from app.models.references import ProjectReference
from app.models.versioning import Asset, AssetRole, VersionState
from app.services import history, licensing, projects
from app.services.authz import require_workspace_role

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
    # F-072: where the work comes from and what may be done with it
    license_id: str | None = None
    attribution: str | None = None
    source_url: str | None = None
    remixed_from_project_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LicenseBody(BaseModel):
    license_id: str | None = Field(default=None, max_length=40)
    attribution: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=500)


class RemixBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)


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


NormalizedPoint = Annotated[float, Field(ge=0, le=1)]


class ReferenceUpdate(BaseModel):
    asset_id: uuid.UUID
    width_px: int = Field(gt=0, le=10000)
    height_px: int = Field(gt=0, le=10000)
    width_mm: float = Field(gt=0, le=1_000_000)
    known_mm: float = Field(default=0, ge=0, le=1_000_000)
    calibration: list[tuple[NormalizedPoint, NormalizedPoint]] = Field(
        default_factory=list, max_length=2
    )
    offset_x: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    offset_z: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    opacity: float = Field(default=0.65, ge=0.15, le=1)
    visible: bool = True

class ReferenceOut(ReferenceUpdate):
    url: str
    updated_at: datetime


def _reference_out(record: ProjectReference, storage: StorageDep, asset: Asset) -> ReferenceOut:
    return ReferenceOut(
        **record.settings,
        asset_id=record.asset_id,
        url=storage.presign_get(asset.storage_key, ttl_seconds=15 * 60),
        updated_at=record.updated_at,
    )


@router.get("/projects/{project_id}/reference", response_model=ReferenceOut | None)
def get_reference(
    project_id: uuid.UUID, db: DbDep, storage: StorageDep, principal: PrincipalDep
) -> ReferenceOut | None:
    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    record = db.get(ProjectReference, project_id)
    if record is None:
        return None
    asset = db.get(Asset, record.asset_id)
    if asset is None:
        raise NotFoundError("asset", record.asset_id)
    return _reference_out(record, storage, asset)


@router.put("/projects/{project_id}/reference", response_model=ReferenceOut)
def put_reference(
    project_id: uuid.UUID,
    body: ReferenceUpdate,
    db: DbDep,
    storage: StorageDep,
    principal: PrincipalDep,
) -> ReferenceOut:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    asset = db.get(Asset, body.asset_id)
    if asset is None or asset.workspace_id != project.workspace_id:
        raise NotFoundError("asset", body.asset_id)
    if asset.mime not in ("image/jpeg", "image/png"):
        raise ValidationFailedError("reference asset must be a JPEG or PNG image")
    record = db.get(ProjectReference, project_id)
    if record is None:
        record = ProjectReference(project_id=project_id, asset_id=body.asset_id)
        db.add(record)
    record.asset_id = body.asset_id
    record.settings = body.model_dump(mode="json", exclude={"asset_id"})
    db.flush()
    db.refresh(record)
    return _reference_out(record, storage, asset)


@router.delete("/projects/{project_id}/reference", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    record = db.get(ProjectReference, project_id)
    if record is not None:
        db.delete(record)


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


class VersionSnapshot(BaseModel):
    """One side of a comparison: the numbers a user reads off the screen."""

    version_id: uuid.UUID
    sequence_no: int
    label: str | None
    state: VersionState
    size_mm: list[float] | None = None
    volume_mm3: float | None = None
    surface_area_mm2: float | None = None
    valid: bool | None = None
    body: str | None = None
    operation: str | None = None
    goal: str | None = None


class VersionComparison(BaseModel):
    before: VersionSnapshot | None
    after: VersionSnapshot
    changed: dict[str, Any]
    edit_operations: list[dict[str, Any]] = Field(default_factory=list)
    awaiting_decision: bool


@router.get("/licences")
def list_licences(principal: PrincipalDep) -> list[dict[str, Any]]:
    """The licences a project can be published or imported under (F-072)."""
    return [vars(lic) for lic in licensing.LICENCES.values()]


@router.put("/projects/{project_id}/license", response_model=ProjectOut)
def set_project_license(
    project_id: uuid.UUID, body: LicenseBody, db: DbDep, principal: PrincipalDep
) -> ProjectOut:
    project = licensing.set_license(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        license_id=body.license_id,
        attribution=body.attribution,
        source_url=body.source_url,
    )
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/license")
def project_license(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> dict[str, Any]:
    """What may be done with this work, given every licence in its remix chain (F-047)."""
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    return licensing.permissions(db, project)


@router.post(
    "/projects/{project_id}/remix", status_code=status.HTTP_201_CREATED, response_model=ProjectOut
)
def remix_project(
    project_id: uuid.UUID, body: RemixBody, db: DbDep, principal: PrincipalDep
) -> ProjectOut:
    """A new project from this one's current model — if the licence allows it (F-047)."""
    project = licensing.remix(db, user_id=principal.user_id, project_id=project_id, name=body.name)
    return ProjectOut.model_validate(project)


class RollbackBody(BaseModel):
    """What to go back to, in the user's words: "два часа назад", "v3", "before the hole"."""

    expression: str = Field(min_length=1, max_length=200)


@router.post(
    "/projects/{project_id}/rollback",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionOut,
)
def rollback_project(
    project_id: uuid.UUID, body: RollbackBody, db: DbDep, principal: PrincipalDep
) -> VersionOut:
    """F-016: an earlier state becomes the current one — as a new version, never by deleting."""
    version = history.rollback(
        db, user_id=principal.user_id, project_id=project_id, expression=body.expression
    )
    return VersionOut.model_validate(version)


@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> VersionOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    return VersionOut.model_validate(version)


class ProvenanceGraphOut(BaseModel):
    """F-079: the versions, the commands, the scans, the origins and the derived work."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]
    summary: dict[str, Any]


@router.get("/projects/{project_id}/graph", response_model=ProvenanceGraphOut)
def project_graph(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ProvenanceGraphOut:
    from app.services import provenance

    built = provenance.graph(db, user_id=principal.user_id, project_id=project_id)
    return ProvenanceGraphOut(**built.to_dict())


@router.get("/versions/{version_id}/lineage", response_model=list[VersionOut])
def get_lineage(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[VersionOut]:
    chain = projects.lineage(db, user_id=principal.user_id, version_id=version_id)
    return [VersionOut.model_validate(v) for v in chain]


@router.post(
    "/versions/{version_id}/finalize",
    response_model=VersionOut,
)
def finalize_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> VersionOut:
    """Accept a draft (T-052): it becomes history and the project head follows it."""
    version = projects.finalize_version_as(db, user_id=principal.user_id, version_id=version_id)
    return VersionOut.model_validate(version)


@router.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    """Reject a preview (T-052). Only a draft can go; finalized history never can."""
    projects.discard_version(db, user_id=principal.user_id, version_id=version_id)


@router.get("/versions/{version_id}/compare", response_model=VersionComparison)
def compare_version(
    version_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    against: uuid.UUID | None = None,
) -> VersionComparison:
    """Before and after (T-052): this version against the one it was built from."""
    return VersionComparison.model_validate(
        projects.compare_versions(
            db, user_id=principal.user_id, version_id=version_id, against_id=against
        )
    )
