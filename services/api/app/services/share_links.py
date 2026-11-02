"""Revocable, expiring read-only project share links (reference 62/64).

A link proves only the right to view one project's current head version — never workspace
membership, editing, comments, or any other project in the workspace. Creating or revoking a
link is restricted to the project's workspace owner, since it is the one action that can expose
a project outside the workspace entirely.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.auth import hash_token
from app.models.core import Project, WorkspaceRole
from app.models.share_links import ProjectShareLink
from app.services import projects
from app.services.authz import require_workspace_role

TOKEN_PREFIX = "shr_"
MIN_EXPIRES_HOURS = 1
MAX_EXPIRES_HOURS = 24 * 30


@dataclass(frozen=True, slots=True)
class ResolvedShareLink:
    link: ProjectShareLink
    project: Project


def create_share_link(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, expires_in_hours: int
) -> tuple[ProjectShareLink, str]:
    if not MIN_EXPIRES_HOURS <= expires_in_hours <= MAX_EXPIRES_HOURS:
        raise ValidationFailedError(
            "share-link expiry must be between 1 and 720 hours",
            {"expires_in_hours": expires_in_hours},
        )
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.owner)
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    link = ProjectShareLink(
        project_id=project.id,
        token_hash=hash_token(plaintext),
        created_by=user_id,
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
    )
    db.add(link)
    db.flush()
    return link, plaintext


def list_share_links(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> list[ProjectShareLink]:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.owner)
    return list(
        db.scalars(
            sa.select(ProjectShareLink)
            .where(ProjectShareLink.project_id == project.id)
            .order_by(ProjectShareLink.created_at.desc())
        )
    )


def revoke_share_link(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, link_id: uuid.UUID
) -> None:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.owner)
    link = db.get(ProjectShareLink, link_id)
    if link is None or link.project_id != project.id:
        raise NotFoundError("share_link", link_id)
    if link.revoked_at is None:
        link.revoked_at = datetime.now(UTC)
        db.flush()


def resolve_share_link(db: Session, *, token: str) -> ResolvedShareLink | None:
    """Return the project a live, unexpired, unrevoked token grants read access to."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    link = db.scalar(
        sa.select(ProjectShareLink).where(ProjectShareLink.token_hash == hash_token(token))
    )
    if link is None or link.revoked_at is not None:
        return None
    if link.expires_at <= datetime.now(UTC):
        return None
    project = db.get(Project, link.project_id)
    if project is None or project.deleted_at is not None:
        return None
    link.last_used_at = datetime.now(UTC)
    db.flush()
    return ResolvedShareLink(link=link, project=project)
