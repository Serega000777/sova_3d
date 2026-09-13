"""Workspace authorization. Every project/version/asset action goes through here.

Rule from docs/05 §4: authorize in the service layer, never by opaque id alone.
A missing membership is reported as "not found" so workspace ids cannot be
probed from outside.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ForbiddenError, NotFoundError
from app.models.core import WorkspaceMember, WorkspaceRole

# Higher rank may do everything a lower rank may.
_RANK = {
    WorkspaceRole.viewer: 0,
    WorkspaceRole.editor: 1,
    WorkspaceRole.admin: 2,
    WorkspaceRole.owner: 3,
}


def role_in_workspace(
    session: Session, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> WorkspaceRole | None:
    return session.scalar(
        sa.select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    )


def require_workspace_role(
    session: Session,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    minimum: WorkspaceRole,
) -> WorkspaceRole:
    role = role_in_workspace(session, user_id, workspace_id)
    if role is None:
        raise NotFoundError("workspace", workspace_id)
    if _RANK[role] < _RANK[minimum]:
        raise ForbiddenError(f"requires {minimum.value} role in workspace")
    return role
