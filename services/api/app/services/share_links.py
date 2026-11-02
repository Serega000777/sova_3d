"""Revocable, expiring read-only links (references 62/64/90/97).

A `ProjectShareLink` proves only the right to view one project's current head version — never
workspace membership, editing, comments, or any other project. An `IntegrityVerificationLink`
proves only the right to read one version's latest persisted integrity-check report, the same
facts already in the authenticated PDF, without a cryptographic signature. Creating or revoking
either kind is restricted to the project's workspace owner, since both expose something outside
the workspace entirely.
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
from app.models.share_links import IntegrityVerificationLink, ProjectShareLink
from app.models.versioning import ProjectVersion
from app.services import projects
from app.services.authz import require_workspace_role

TOKEN_PREFIX = "shr_"
VERIFY_TOKEN_PREFIX = "vrf_"
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


@dataclass(frozen=True, slots=True)
class ResolvedVerificationLink:
    link: IntegrityVerificationLink
    version: ProjectVersion
    project: Project


def _owned_version(db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID) -> ProjectVersion:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.owner)
    return version


def create_verification_link(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID, expires_in_hours: int
) -> tuple[IntegrityVerificationLink, str]:
    if not MIN_EXPIRES_HOURS <= expires_in_hours <= MAX_EXPIRES_HOURS:
        raise ValidationFailedError(
            "verification-link expiry must be between 1 and 720 hours",
            {"expires_in_hours": expires_in_hours},
        )
    version = _owned_version(db, user_id=user_id, version_id=version_id)
    plaintext = VERIFY_TOKEN_PREFIX + secrets.token_urlsafe(32)
    link = IntegrityVerificationLink(
        version_id=version.id,
        token_hash=hash_token(plaintext),
        created_by=user_id,
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
    )
    db.add(link)
    db.flush()
    return link, plaintext


def list_verification_links(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID
) -> list[IntegrityVerificationLink]:
    version = _owned_version(db, user_id=user_id, version_id=version_id)
    return list(
        db.scalars(
            sa.select(IntegrityVerificationLink)
            .where(IntegrityVerificationLink.version_id == version.id)
            .order_by(IntegrityVerificationLink.created_at.desc())
        )
    )


def revoke_verification_link(
    db: Session, *, user_id: uuid.UUID, version_id: uuid.UUID, link_id: uuid.UUID
) -> None:
    version = _owned_version(db, user_id=user_id, version_id=version_id)
    link = db.get(IntegrityVerificationLink, link_id)
    if link is None or link.version_id != version.id:
        raise NotFoundError("verification_link", link_id)
    if link.revoked_at is None:
        link.revoked_at = datetime.now(UTC)
        db.flush()


def resolve_verification_link(db: Session, *, token: str) -> ResolvedVerificationLink | None:
    """Return the version a live, unexpired, unrevoked token grants report-reading access to."""
    if not token.startswith(VERIFY_TOKEN_PREFIX):
        return None
    link = db.scalar(
        sa.select(IntegrityVerificationLink).where(
            IntegrityVerificationLink.token_hash == hash_token(token)
        )
    )
    if link is None or link.revoked_at is not None:
        return None
    if link.expires_at <= datetime.now(UTC):
        return None
    version = db.get(ProjectVersion, link.version_id)
    if version is None:
        return None
    project = db.get(Project, version.project_id)
    if project is None or project.deleted_at is not None:
        return None
    link.last_used_at = datetime.now(UTC)
    db.flush()
    return ResolvedVerificationLink(link=link, version=version, project=project)
