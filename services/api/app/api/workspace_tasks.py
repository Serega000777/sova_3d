"""Revision-guarded task list for one team workspace (reference 64)."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import Workspace, WorkspaceKind, WorkspaceRole
from app.models.workspace_tasks import WorkspaceTask
from app.services.authz import require_workspace_role

router = APIRouter(prefix="/workspaces/{workspace_id}/tasks", tags=["workspace-tasks"])
MAX_VISIBLE_TASKS = 100


class WorkspaceTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class WorkspaceTaskUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    completed: bool | None = None

    @model_validator(mode="after")
    def _has_change(self) -> "WorkspaceTaskUpdate":
        if self.title is None and self.completed is None:
            raise ValueError("a task update must change title or completion")
        return self


class WorkspaceTaskOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    completed: bool
    completed_at: datetime | None
    revision: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class WorkspaceTaskListOut(BaseModel):
    open_count: int
    total_count: int
    tasks: list[WorkspaceTaskOut]


def _team(
    db: DbDep,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    minimum: WorkspaceRole,
) -> Workspace:
    require_workspace_role(db, user_id, workspace_id, minimum)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("workspace", workspace_id)
    if workspace.kind is not WorkspaceKind.team:
        raise ValidationFailedError("personal workspaces do not have team tasks")
    return workspace


def _out(task: WorkspaceTask) -> WorkspaceTaskOut:
    return WorkspaceTaskOut(
        id=task.id,
        workspace_id=task.workspace_id,
        title=task.title,
        completed=task.completed_at is not None,
        completed_at=task.completed_at,
        revision=task.revision,
        created_by=task.created_by,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("", response_model=WorkspaceTaskListOut)
def list_workspace_tasks(
    workspace_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> WorkspaceTaskListOut:
    _team(db, principal.user_id, workspace_id, WorkspaceRole.viewer)
    open_count = db.scalar(
        sa.select(sa.func.count())
        .select_from(WorkspaceTask)
        .where(
            WorkspaceTask.workspace_id == workspace_id,
            WorkspaceTask.completed_at.is_(None),
        )
    )
    total_count = db.scalar(
        sa.select(sa.func.count())
        .select_from(WorkspaceTask)
        .where(WorkspaceTask.workspace_id == workspace_id)
    )
    tasks = db.scalars(
        sa.select(WorkspaceTask)
        .where(WorkspaceTask.workspace_id == workspace_id)
        .order_by(
            WorkspaceTask.completed_at.is_not(None),
            WorkspaceTask.updated_at.desc(),
            WorkspaceTask.id,
        )
        .limit(MAX_VISIBLE_TASKS)
    ).all()
    return WorkspaceTaskListOut(
        open_count=int(open_count or 0),
        total_count=int(total_count or 0),
        tasks=[_out(task) for task in tasks],
    )


@router.post("", response_model=WorkspaceTaskOut, status_code=status.HTTP_201_CREATED)
def create_workspace_task(
    workspace_id: uuid.UUID,
    body: WorkspaceTaskCreate,
    db: DbDep,
    principal: PrincipalDep,
) -> WorkspaceTaskOut:
    _team(db, principal.user_id, workspace_id, WorkspaceRole.editor)
    title = body.title.strip()
    if not title:
        raise ValidationFailedError("task title must not be blank")
    task = WorkspaceTask(
        workspace_id=workspace_id,
        title=title,
        created_by=principal.user_id,
    )
    db.add(task)
    db.flush()
    return _out(task)


@router.patch("/{task_id}", response_model=WorkspaceTaskOut)
def update_workspace_task(
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    body: WorkspaceTaskUpdate,
    db: DbDep,
    principal: PrincipalDep,
) -> WorkspaceTaskOut:
    _team(db, principal.user_id, workspace_id, WorkspaceRole.editor)
    task = db.scalar(
        sa.select(WorkspaceTask)
        .where(
            WorkspaceTask.id == task_id,
            WorkspaceTask.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if task is None:
        raise NotFoundError("workspace task", task_id)
    if task.revision != body.expected_revision:
        raise ConflictError("workspace task changed; reload before updating")
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise ValidationFailedError("task title must not be blank")
        task.title = title
    if body.completed is not None:
        if body.completed and task.completed_at is None:
            task.completed_at = datetime.now(UTC)
        elif not body.completed:
            task.completed_at = None
    task.revision += 1
    db.flush()
    return _out(task)
