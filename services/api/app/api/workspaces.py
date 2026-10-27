"""Owner-managed access to an existing team workspace (reference 62)."""

import uuid
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import User, Workspace, WorkspaceKind, WorkspaceMember, WorkspaceRole
from app.services.authz import require_workspace_role
from app.services.signin import normalize_email

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
AssignableRole = Literal["admin", "editor", "viewer"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: WorkspaceRole
    created_at: str


class MemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: AssignableRole = "viewer"


class MemberUpdate(BaseModel):
    role: AssignableRole


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: WorkspaceKind
    role: WorkspaceRole


def _team(db: DbDep, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.viewer)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("workspace", workspace_id)
    if workspace.kind is not WorkspaceKind.team:
        raise ValidationFailedError("personal workspaces do not have a team directory")
    return workspace


def _team_owned(db: DbDep, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.owner)
    workspace = db.scalar(
        sa.select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise NotFoundError("workspace", workspace_id)
    if workspace.kind is not WorkspaceKind.team:
        raise ValidationFailedError("personal workspaces cannot be shared")
    return workspace


def _out(member: WorkspaceMember, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=member.role,
        created_at=member.created_at.isoformat(),
    )


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_team_workspace(
    body: WorkspaceCreate, db: DbDep, principal: PrincipalDep
) -> WorkspaceOut:
    name = body.name.strip()
    if not name:
        raise ValidationFailedError("workspace name must not be blank")
    workspace = Workspace(
        name=name,
        kind=WorkspaceKind.team,
        owner_user_id=principal.user_id,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=principal.user_id,
            role=WorkspaceRole.owner,
        )
    )
    db.flush()
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        kind=workspace.kind,
        role=WorkspaceRole.owner,
    )


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(workspace_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> list[MemberOut]:
    _team(db, principal.user_id, workspace_id)
    rows = db.execute(
        sa.select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(
            sa.case(
                (WorkspaceMember.role == WorkspaceRole.owner, 0),
                (WorkspaceMember.role == WorkspaceRole.admin, 1),
                (WorkspaceMember.role == WorkspaceRole.editor, 2),
                else_=3,
            ),
            User.email.nulls_last(),
            User.id,
        )
    )
    return [_out(member, user) for member, user in rows]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: uuid.UUID, body: MemberCreate, db: DbDep, principal: PrincipalDep
) -> MemberOut:
    workspace = _team_owned(db, principal.user_id, workspace_id)
    email = normalize_email(body.email)
    user = db.scalar(sa.select(User).where(User.email == email))
    if user is None:
        raise NotFoundError("registered user", email)
    existing = db.get(WorkspaceMember, (workspace_id, user.id))
    if existing is not None:
        raise ConflictError("user is already a workspace member")
    member = WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole(body.role))
    db.add(member)
    db.flush()
    return _out(member, user)


def _mutable_member(db: DbDep, workspace_id: uuid.UUID, user_id: uuid.UUID) -> WorkspaceMember:
    member = db.scalar(
        sa.select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .with_for_update()
    )
    if member is None:
        raise NotFoundError("workspace member", user_id)
    if member.role is WorkspaceRole.owner:
        raise ValidationFailedError("workspace owner access cannot be changed")
    return member


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    db: DbDep,
    principal: PrincipalDep,
) -> MemberOut:
    _team_owned(db, principal.user_id, workspace_id)
    member = _mutable_member(db, workspace_id, user_id)
    member.role = WorkspaceRole(body.role)
    db.flush()
    return _out(member, member.user)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: uuid.UUID, user_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> Response:
    _team_owned(db, principal.user_id, workspace_id)
    member = _mutable_member(db, workspace_id, user_id)
    db.delete(member)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
