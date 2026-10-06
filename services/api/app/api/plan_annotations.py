"""Plan markup endpoints (T-237b/T-238, F-087).

Mirrors `Annotation[]` in packages/contracts/src/floor-plan.ts: one JSONB array per
(project, plan), shared across devices instead of living only in browser localStorage. Writes
are compare-and-swap by revision, then announced through the project's existing live room.
"""

import math
import uuid
from datetime import datetime
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import DbDep, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import WorkspaceRole
from app.models.plan_annotations import PlanAnnotations
from app.models.versioning import Asset, ProjectVersion
from app.services import projects
from app.services.authz import require_workspace_role

router = APIRouter(tags=["plan-annotations"])

Point = tuple[float, float]


class AnnotationBase(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    author: str = Field(default="", max_length=200)
    created_at: str
    status: Literal["open", "resolved"] = "open"
    note: str = Field(default="", max_length=4000)
    colour: str = Field(max_length=20)
    photo_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    model_anchor_mm: tuple[float, float, float] | None = None
    model_version_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _anchor_belongs_to_a_version(self) -> "AnnotationBase":
        if (self.model_anchor_mm is None) != (self.model_version_id is None):
            raise ValueError("model_anchor_mm and model_version_id must be set together")
        if self.model_anchor_mm is not None and any(
            not math.isfinite(value) or abs(value) > 1_000_000 for value in self.model_anchor_mm
        ):
            raise ValueError("model anchor coordinates must be finite and within 1000 m")
        return self


class PinAnnotation(AnnotationBase):
    kind: Literal["pin"]
    at: Point
    number: float


class CloudRectAnnotation(AnnotationBase):
    kind: Literal["cloud", "rect"]
    from_: Point = Field(alias="from")
    to: Point
    model_config = {"populate_by_name": True}


class CircleAnnotation(AnnotationBase):
    kind: Literal["circle"]
    centre: Point
    radius_mm: float = Field(gt=0)


class ArrowDimensionAnnotation(AnnotationBase):
    kind: Literal["arrow", "dimension"]
    from_: Point = Field(alias="from")
    to: Point
    model_config = {"populate_by_name": True}


class FreehandAnnotation(AnnotationBase):
    kind: Literal["freehand"]
    points: list[Point] = Field(min_length=2, max_length=5000)


class TextAnnotation(AnnotationBase):
    kind: Literal["text"]
    at: Point
    text: str = Field(max_length=2000)
    size_mm: float = Field(gt=0)


Annotation = Annotated[
    PinAnnotation
    | CloudRectAnnotation
    | CircleAnnotation
    | ArrowDimensionAnnotation
    | FreehandAnnotation
    | TextAnnotation,
    Field(discriminator="kind"),
]


class PlanAnnotationsUpdate(BaseModel):
    annotations: list[Annotation] = Field(default_factory=list, max_length=5000)
    base_revision: int = Field(ge=0)


class PlanAnnotationsOut(PlanAnnotationsUpdate):
    base_revision: int = Field(default=0, exclude=True)
    revision: int = 0
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None

    model_config = {"from_attributes": True}


def _get_record(db: Session, project_id: uuid.UUID, plan_id: str) -> PlanAnnotations | None:
    return db.scalar(
        sa.select(PlanAnnotations).where(
            PlanAnnotations.project_id == project_id, PlanAnnotations.plan_id == plan_id
        )
    )


@router.get("/projects/{project_id}/plans/{plan_id}/annotations", response_model=PlanAnnotationsOut)
def get_plan_annotations(
    project_id: uuid.UUID, plan_id: str, db: DbDep, principal: PrincipalDep
) -> PlanAnnotationsOut:
    projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    record = _get_record(db, project_id, plan_id)
    if record is None:
        return PlanAnnotationsOut(annotations=[], revision=0)
    return PlanAnnotationsOut.model_validate(record)


@router.put("/projects/{project_id}/plans/{plan_id}/annotations", response_model=PlanAnnotationsOut)
def put_plan_annotations(
    project_id: uuid.UUID,
    plan_id: str,
    body: PlanAnnotationsUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbDep,
    principal: PrincipalDep,
) -> PlanAnnotationsOut:
    project = projects.get_project(db, user_id=principal.user_id, project_id=project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    asset_ids = {
        asset_id for annotation in body.annotations for asset_id in annotation.photo_asset_ids
    }
    if asset_ids:
        assets = {
            asset.id: asset
            for asset in db.scalars(sa.select(Asset).where(Asset.id.in_(asset_ids))).all()
        }
        for asset_id in asset_ids:
            asset = assets.get(asset_id)
            if asset is None or asset.workspace_id != project.workspace_id:
                raise NotFoundError("asset", asset_id)
            if asset.format not in {"jpeg", "png"} or not asset.mime.startswith("image/"):
                raise ValidationFailedError(
                    "annotation photos must be JPEG or PNG image assets",
                    {"asset_id": str(asset_id), "format": asset.format},
                )
    version_ids = {
        annotation.model_version_id
        for annotation in body.annotations
        if annotation.model_version_id is not None
    }
    if version_ids:
        versions = {
            version.id: version
            for version in db.scalars(
                sa.select(ProjectVersion).where(ProjectVersion.id.in_(version_ids))
            ).all()
        }
        for version_id in version_ids:
            version = versions.get(version_id)
            if version is None or version.project_id != project.id:
                raise NotFoundError("project_version", version_id)
    dumped = [a.model_dump(mode="json", by_alias=True) for a in body.annotations]
    create_or_update = insert(PlanAnnotations).values(
        project_id=project_id,
        plan_id=plan_id,
        annotations=dumped,
        revision=1,
        updated_by=principal.user_id,
    )
    statement = create_or_update.on_conflict_do_update(
        constraint="uq_plan_annotations_project_plan",
        set_={
            "annotations": create_or_update.excluded.annotations,
            "revision": PlanAnnotations.revision + 1,
            "updated_by": create_or_update.excluded.updated_by,
            "updated_at": sa.func.now(),
        },
        where=PlanAnnotations.revision == body.base_revision,
    ).returning(
        PlanAnnotations.annotations,
        PlanAnnotations.revision,
        PlanAnnotations.updated_at,
        PlanAnnotations.updated_by,
    )
    row = db.execute(statement).mappings().one_or_none()
    if row is None:
        current = _get_record(db, project_id, plan_id)
        raise ConflictError(
            "plan annotations changed since they were loaded",
            {
                "plan_id": plan_id,
                "base_revision": body.base_revision,
                "current_revision": current.revision if current is not None else 0,
            },
        )
    result = PlanAnnotationsOut(
        annotations=row["annotations"],
        revision=row["revision"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )
    broker = request.app.state.live_broker
    background_tasks.add_task(
        broker.publish,
        str(project_id),
        {
            "type": "plan_annotations",
            "plan_id": plan_id,
            "revision": result.revision,
            "updated_by": str(principal.user_id),
            "updated_at": result.updated_at.isoformat() if result.updated_at is not None else None,
        },
    )
    return result
