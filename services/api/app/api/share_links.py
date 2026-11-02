"""Revocable, expiring read-only project share links (reference 62/64).

Creating, listing and revoking a link require the project's workspace owner. Resolving a link
needs no bearer token at all — the link's own secret is the only credential — and proves nothing
beyond read access to that one project's current head version. It never creates a session,
workspace membership, or any write path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, StorageDep
from app.api.errors import NotFoundError
from app.services import projects, share_links
from app.services.assets import REPAIRABLE_FORMATS, model_asset_of, preview_asset_of

router = APIRouter(tags=["share-links"])


class ShareLinkCreate(BaseModel):
    expires_in_hours: int = Field(
        default=24 * 7, ge=share_links.MIN_EXPIRES_HOURS, le=share_links.MAX_EXPIRES_HOURS
    )


class ShareLinkCreated(BaseModel):
    id: uuid.UUID
    token: str
    expires_at: datetime


class ShareLinkOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class SharedModelOut(BaseModel):
    format: str
    download_url: str
    expires_in_seconds: int


class SharedProjectOut(BaseModel):
    project_name: str
    description: str | None
    version_id: uuid.UUID
    version_created_at: datetime
    link_expires_at: datetime
    model: SharedModelOut | None


@router.post(
    "/projects/{project_id}/share-links",
    response_model=ShareLinkCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_project_share_link(
    project_id: uuid.UUID, body: ShareLinkCreate, db: DbDep, principal: PrincipalDep
) -> ShareLinkCreated:
    link, token = share_links.create_share_link(
        db,
        user_id=principal.user_id,
        project_id=project_id,
        expires_in_hours=body.expires_in_hours,
    )
    return ShareLinkCreated(id=link.id, token=token, expires_at=link.expires_at)


@router.get("/projects/{project_id}/share-links", response_model=list[ShareLinkOut])
def list_project_share_links(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[ShareLinkOut]:
    links = share_links.list_share_links(db, user_id=principal.user_id, project_id=project_id)
    return [
        ShareLinkOut(
            id=link.id,
            created_at=link.created_at,
            expires_at=link.expires_at,
            revoked_at=link.revoked_at,
            last_used_at=link.last_used_at,
        )
        for link in links
    ]


@router.delete(
    "/projects/{project_id}/share-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_project_share_link(
    project_id: uuid.UUID, link_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> None:
    share_links.revoke_share_link(
        db, user_id=principal.user_id, project_id=project_id, link_id=link_id
    )


@router.get("/share/{token}", response_model=SharedProjectOut)
def open_shared_project(token: str, db: DbDep, storage: StorageDep) -> SharedProjectOut:
    """Public, bearer-token-free read access. The link secret is the only credential."""
    resolved = share_links.resolve_share_link(db, token=token)
    if resolved is None:
        raise NotFoundError("share_link", token)
    project = resolved.project
    if project.head_version_id is None:
        raise NotFoundError("share_link", token)
    version = projects.get_version(
        db, user_id=resolved.link.created_by, version_id=project.head_version_id
    )
    asset = preview_asset_of(db, version) or model_asset_of(db, version)
    model: SharedModelOut | None = None
    if asset is not None and asset.format in REPAIRABLE_FORMATS:
        ttl = 15 * 60
        model = SharedModelOut(
            format=asset.format,
            download_url=storage.presign_get(asset.storage_key, ttl_seconds=ttl),
            expires_in_seconds=ttl,
        )
    return SharedProjectOut(
        project_name=project.name,
        description=project.description,
        version_id=version.id,
        version_created_at=version.created_at,
        link_expires_at=resolved.link.expires_at,
        model=model,
    )
