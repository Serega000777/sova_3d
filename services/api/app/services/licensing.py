"""Source and licence metadata (T-133, F-072) and remixing legally (T-134, F-047).

A project knows where its work came from — the licence it was published under, whom to
credit, the URL it was taken from and the project it was remixed from — and the platform
reads the licence before letting a remix happen: no derivatives means no remix, share-alike
means the remix carries the same licence, attribution means the credit line is written for
you, non-commercial follows the work wherever it goes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.models.core import Project, WorkspaceRole
from app.models.execution import Operation
from app.models.versioning import ProjectVersion
from app.services import projects
from app.services.authz import require_workspace_role


@dataclass(frozen=True)
class Licence:
    id: str
    name: str
    url: str
    commercial_use: bool
    derivatives: bool
    share_alike: bool
    attribution_required: bool


LICENCES: dict[str, Licence] = {
    lic.id: lic
    for lic in (
        Licence(
            "CC0-1.0",
            "CC0 1.0 (public domain)",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            True,
            True,
            False,
            False,
        ),
        Licence(
            "CC-BY-4.0",
            "CC BY 4.0",
            "https://creativecommons.org/licenses/by/4.0/",
            True,
            True,
            False,
            True,
        ),
        Licence(
            "CC-BY-SA-4.0",
            "CC BY-SA 4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/",
            True,
            True,
            True,
            True,
        ),
        Licence(
            "CC-BY-NC-4.0",
            "CC BY-NC 4.0",
            "https://creativecommons.org/licenses/by-nc/4.0/",
            False,
            True,
            False,
            True,
        ),
        Licence(
            "CC-BY-NC-SA-4.0",
            "CC BY-NC-SA 4.0",
            "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            False,
            True,
            True,
            True,
        ),
        Licence(
            "CC-BY-ND-4.0",
            "CC BY-ND 4.0",
            "https://creativecommons.org/licenses/by-nd/4.0/",
            True,
            False,
            False,
            True,
        ),
        Licence(
            "CC-BY-NC-ND-4.0",
            "CC BY-NC-ND 4.0",
            "https://creativecommons.org/licenses/by-nc-nd/4.0/",
            False,
            False,
            False,
            True,
        ),
        Licence("MIT", "MIT", "https://opensource.org/license/mit", True, True, False, True),
        Licence(
            "GPL-3.0-or-later",
            "GPL 3.0 or later",
            "https://www.gnu.org/licenses/gpl-3.0.html",
            True,
            True,
            True,
            True,
        ),
        Licence("all-rights-reserved", "All rights reserved", "", False, False, False, True),
    )
}
# A project that names no licence is the author's own work: theirs to do anything with.
OWN_WORK = Licence("own-work", "Your own work", "", True, True, False, False)


def licence_of(project: Project) -> Licence:
    if not project.license_id:
        return OWN_WORK
    return LICENCES.get(project.license_id, OWN_WORK)


def set_license(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    license_id: str | None,
    attribution: str | None,
    source_url: str | None,
) -> Project:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if license_id is not None and license_id not in LICENCES:
        raise ValidationFailedError(f"unknown licence {license_id!r}", {"known": sorted(LICENCES)})
    if license_id and LICENCES[license_id].attribution_required and not (attribution or "").strip():
        raise ValidationFailedError(
            f"{LICENCES[license_id].name} requires attribution: say whom to credit"
        )
    project.license_id = license_id
    project.attribution = (attribution or "").strip() or None
    project.source_url = (source_url or "").strip() or None
    db.flush()
    return project


def chain(db: Session, project: Project) -> list[Project]:
    """The project and everything it was remixed from, nearest first."""
    line = [project]
    seen = {project.id}
    current = project
    while current.remixed_from_project_id and current.remixed_from_project_id not in seen:
        parent = db.get(Project, current.remixed_from_project_id)
        if parent is None:
            break
        line.append(parent)
        seen.add(parent.id)
        current = parent
    return line


def permissions(db: Session, project: Project) -> dict[str, Any]:
    """What may be done with this work, given every licence in its chain (F-047).

    The strictest term wins along the chain: a non-commercial ancestor keeps a remix
    non-commercial; a share-alike ancestor keeps its licence on every remix.
    """
    line = chain(db, project)
    licences = [licence_of(p) for p in line]
    commercial = all(lic.commercial_use for lic in licences)
    derivatives = all(lic.derivatives for lic in licences)
    share_alike = any(lic.share_alike for lic in licences)
    attribution = any(lic.attribution_required for lic in licences)
    credits = [
        f"{p.attribution or p.name} ({licence_of(p).name})"
        for p in line[1:] + ([line[0]] if line[0].attribution else [])
        if licence_of(p).attribution_required or p.attribution
    ]
    notes: list[str] = []
    if not derivatives:
        notes.append("This work may not be changed or remixed (no derivatives).")
    if not commercial:
        notes.append("Not for commercial use — a remix stays non-commercial.")
    if share_alike:
        notes.append("Share-alike: a remix must carry the same licence.")
    if attribution and credits:
        notes.append("Credit: " + "; ".join(dict.fromkeys(credits)))
    return {
        "licence": vars(licence_of(project)),
        "commercial_use": commercial,
        "derivatives": derivatives,
        "share_alike": share_alike,
        "attribution_required": attribution,
        "credits": list(dict.fromkeys(credits)),
        "notes": notes,
        "chain": [
            {
                "project_id": str(p.id),
                "name": p.name,
                "license_id": p.license_id,
                "attribution": p.attribution,
                "source_url": p.source_url,
            }
            for p in line
        ],
    }


def remix(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, name: str | None = None
) -> Project:
    """A new project carrying the head version and the provenance — if the licence allows."""
    source = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, source.workspace_id, WorkspaceRole.editor)
    terms = permissions(db, source)
    if not terms["derivatives"]:
        raise ValidationFailedError(
            "the licence does not allow remixing this work (no derivatives)",
            {"licence": terms["licence"]["id"], "notes": terms["notes"]},
        )
    if source.head_version_id is None:
        raise ValidationFailedError("there is no model to remix yet")
    head = db.get(ProjectVersion, source.head_version_id)
    assert head is not None

    own = licence_of(source)
    new = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=source.workspace_id,
        name=name or f"{source.name} (remix)",
        description=source.description,
    )
    new.remixed_from_project_id = source.id
    # share-alike keeps the licence; otherwise the remix starts as the remixer's own work,
    # still bound by the ancestors' terms through the chain
    new.license_id = source.license_id if terms["share_alike"] else None
    if terms["attribution_required"]:
        new.attribution = "; ".join(terms["credits"])[:300] or (
            f"based on {source.name} ({own.name})"
        )
    new.source_url = source.source_url
    db.flush()

    version = projects.create_version_internal(
        db,
        project_id=new.id,
        parent_version_id=None,
        label=f"Remix of {source.name} v{head.sequence_no}",
        provenance={
            **(head.provenance or {}),
            "operation": "remix",
            "remixed_from_project_id": str(source.id),
            "remixed_from_version_id": str(head.id),
        },
        assets={link.role: link.asset_id for link in head.assets},
        finalize=False,
        created_by=user_id,
    )
    rows = db.scalars(
        sa.select(Operation)
        .where(Operation.project_version_id == head.id)
        .order_by(Operation.sequence_no)
    ).all()
    for row in rows:
        db.add(
            Operation(
                project_version_id=version.id,
                sequence_no=row.sequence_no,
                operation_type=row.operation_type,
                schema_version=row.schema_version,
                params=row.params,
                entity_refs=row.entity_refs,
            )
        )
    db.flush()
    projects.finalize_version(db, version)
    return new
