"""Projects (T-014) and versions (T-015) endpoints under /api/v1."""

import uuid
from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, PrincipalDep, StorageDep
from app.api.errors import NotFoundError, ValidationFailedError
from app.api.schemas import JobAccepted
from app.jobs.thumbnail import THUMBNAIL_JOB
from app.models.core import Units, WorkspaceRole
from app.models.references import ProjectReference
from app.models.versioning import Asset, AssetRole, ThumbnailAngle, VersionAsset, VersionState
from app.services import history, jobs, licensing, project_transfers, projects
from app.services.assets import model_asset_of, preview_asset_of
from app.services.authz import require_workspace_role

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ProjectTransferBody(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=320)
    confirmation_name: str = Field(min_length=1, max_length=200)


class ProjectTransferOut(BaseModel):
    source_project_id: uuid.UUID
    target_project_id: uuid.UUID
    recipient_email: str
    version_count: int
    asset_count: int
    transferred_at: datetime


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
    thumbnail_asset_id: uuid.UUID | None = None
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
    # Preserve the pre-angle JSON shape for every non-thumbnail attachment.
    thumbnail_angle: ThumbnailAngle | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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


class VersionHistoryItem(VersionOut):
    creator_name: str | None = None
    comment: str = ""
    comment_revision: int = 0
    comment_updated_at: datetime | None = None
    comment_updated_by: uuid.UUID | None = None
    total_asset_bytes: int = Field(ge=0)


class VersionCommentUpdate(BaseModel):
    comment: str = Field(default="", max_length=2000)
    base_revision: int = Field(ge=0)


class VersionCommentOut(BaseModel):
    comment: str
    revision: int
    updated_at: datetime
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class ProjectSummary(ProjectOut):
    head_version: VersionOut | None


def _thumbnail_asset_ids(db: DbDep, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not version_ids:
        return {}
    rows = db.execute(
        sa.select(VersionAsset.version_id, VersionAsset.asset_id)
        .where(
            VersionAsset.version_id.in_(version_ids),
            VersionAsset.role == AssetRole.thumbnail,
            sa.or_(
                VersionAsset.thumbnail_angle == ThumbnailAngle.iso.value,
                VersionAsset.thumbnail_angle.is_(None),
            ),
        )
        .order_by(
            VersionAsset.version_id,
            sa.case((VersionAsset.thumbnail_angle == ThumbnailAngle.iso.value, 0), else_=1),
            VersionAsset.created_at.desc(),
        )
    ).all()
    result: dict[uuid.UUID, uuid.UUID] = {}
    for version_id, asset_id in rows:
        result.setdefault(version_id, asset_id)
    return result


def _project_out(project: Any, thumbnail_asset_id: uuid.UUID | None) -> ProjectOut:
    return ProjectOut(
        **ProjectOut.model_validate(project).model_dump(exclude={"thumbnail_asset_id"}),
        thumbnail_asset_id=thumbnail_asset_id,
    )


NormalizedPoint = Annotated[float, Field(ge=0, le=1)]


class ReferenceMeasurement(BaseModel):
    id: uuid.UUID
    label: str = Field(min_length=1, max_length=80)
    points: tuple[
        tuple[NormalizedPoint, NormalizedPoint],
        tuple[NormalizedPoint, NormalizedPoint],
    ]
    model_config = {"str_strip_whitespace": True}


class ReferenceUpdate(BaseModel):
    asset_id: uuid.UUID
    width_px: int = Field(gt=0, le=10000)
    height_px: int = Field(gt=0, le=10000)
    width_mm: float = Field(gt=0, le=1_000_000)
    known_mm: float = Field(default=0, ge=0, le=1_000_000)
    calibration: list[tuple[NormalizedPoint, NormalizedPoint]] = Field(
        default_factory=list, max_length=2
    )
    measurements: list[ReferenceMeasurement] = Field(default_factory=list, max_length=100)
    offset_x: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    offset_z: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    opacity: float = Field(default=0.65, ge=0.15, le=1)
    visible: bool = True

    @model_validator(mode="after")
    def unique_measurements(self) -> "ReferenceUpdate":
        ids = [measurement.id for measurement in self.measurements]
        if len(ids) != len(set(ids)):
            raise ValueError("reference measurement ids must be unique")
        return self


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
    thumbnail_ids = _thumbnail_asset_ids(
        db, [project.head_version_id for project in rows if project.head_version_id is not None]
    )
    return [
        _project_out(
            project,
            thumbnail_ids.get(project.head_version_id)
            if project.head_version_id is not None
            else None,
        )
        for project in rows
    ]


@router.get("/projects/{project_id}", response_model=ProjectSummary)
def get_project(project_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ProjectSummary:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    head = (
        projects.get_version(db, user_id=principal.user_id, version_id=project.head_version_id)
        if project.head_version_id
        else None
    )
    thumbnail_ids = _thumbnail_asset_ids(
        db, [project.head_version_id] if project.head_version_id is not None else []
    )
    return ProjectSummary(
        **_project_out(
            project,
            thumbnail_ids.get(project.head_version_id)
            if project.head_version_id is not None
            else None,
        ).model_dump(),
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


@router.post("/projects/{project_id}/transfer", response_model=ProjectTransferOut)
def transfer_project(
    project_id: uuid.UUID,
    body: ProjectTransferBody,
    db: DbDep,
    storage: StorageDep,
    principal: PrincipalDep,
) -> ProjectTransferOut:
    """Move a complete immutable project history to an existing user's personal workspace."""
    result = project_transfers.transfer_project(
        db,
        storage,
        user_id=principal.user_id,
        project_id=project_id,
        recipient_email=body.recipient_email,
        confirmation_name=body.confirmation_name,
    )
    return ProjectTransferOut.model_validate(result, from_attributes=True)


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


@router.get("/projects/{project_id}/version-history", response_model=list[VersionHistoryItem])
def list_version_history(
    project_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[VersionHistoryItem]:
    rows = projects.list_version_history(
        db, user_id=principal.user_id, project_id=project_id, limit=limit, offset=offset
    )
    result: list[VersionHistoryItem] = []
    for row in rows:
        note = row["comment"]
        result.append(
            VersionHistoryItem(
                **VersionOut.model_validate(row["version"]).model_dump(),
                creator_name=row["creator_name"],
                comment=note.comment if note is not None else "",
                comment_revision=note.revision if note is not None else 0,
                comment_updated_at=note.updated_at if note is not None else None,
                comment_updated_by=note.updated_by if note is not None else None,
                total_asset_bytes=row["total_asset_bytes"],
            )
        )
    return result


@router.put("/versions/{version_id}/comment", response_model=VersionCommentOut)
def put_version_comment(
    version_id: uuid.UUID,
    body: VersionCommentUpdate,
    db: DbDep,
    principal: PrincipalDep,
) -> VersionCommentOut:
    note = projects.put_version_comment(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        comment=body.comment.strip(),
        base_revision=body.base_revision,
    )
    return VersionCommentOut.model_validate(note)


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
    # Interactive undo/redo controls know which immutable head they were rendered for.
    # Keeping this optional preserves conversational/history clients while allowing touch
    # clients to fail closed instead of restoring an unexpected concurrently-created head.
    base_version_id: uuid.UUID | None = None


@router.post(
    "/projects/{project_id}/rollback",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionOut,
)
def rollback_project(
    project_id: uuid.UUID, body: RollbackBody, db: DbDep, principal: PrincipalDep
) -> VersionOut:
    """F-016: an earlier state becomes the current one — as a new version, never by deleting."""
    from app.services import entitlements

    entitlements.require(db, principal.user_id, entitlements.Capability.history_restore)
    version = history.rollback(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        expression=body.expression,
        base_version_id=body.base_version_id,
    )
    return VersionOut.model_validate(version)


@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(version_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> VersionOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    return VersionOut.model_validate(version)


@router.post(
    "/versions/{version_id}/thumbnail",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def ensure_version_thumbnail(
    version_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
) -> JobAccepted:
    """Queue the fixed canonical front/iso/top PNG set; repeated calls reuse one job."""
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    source = preview_asset_of(db, version) or model_asset_of(db, version)
    if source is None or source.format not in {
        "stl",
        "obj",
        "ply",
        "glb",
        "gltf",
        "3mf",
        "dae",
        "usdz",
        "x3d",
        "x3dv",
        "wrl",
        "fbx",
        "abc",
    }:
        raise ValidationFailedError("version has no renderable model asset")
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        job_type=THUMBNAIL_JOB,
        input={"version_id": str(version.id), "asset_id": str(source.id)},
        created_by=principal.user_id,
        project_id=project.id,
        project_version_id=version.id,
        idempotency_key=f"thumbnails-v2:{version.id}:{source.id}",
        max_attempts=2,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


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
    from app.services import entitlements

    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    # A draft comparison is part of the safe preview/accept flow on every plan. Historical
    # comparisons between kept versions are the paid history-inspection capability.
    if version.state is not VersionState.draft:
        entitlements.require(db, principal.user_id, entitlements.Capability.version_compare)
    return VersionComparison.model_validate(
        projects.compare_versions(
            db, user_id=principal.user_id, version_id=version_id, against_id=against
        )
    )
