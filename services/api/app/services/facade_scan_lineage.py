"""Server-owned exterior-scan lineage for immutable facade edits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.core import Project
from app.models.execution import Job, JobStatus
from app.models.scanning import ScanSession, ScanStatus
from app.models.versioning import Asset, AssetRole, ProjectVersion, VersionAsset

FACADE_JOB = "edit_facade"
PROMOTION_METHOD = "manual_metric_facade_trace"


class FacadeScanLineageError(ValueError):
    """The claimed scan cannot be proved from immutable server-owned records."""


@dataclass(frozen=True)
class FacadeScanLineage:
    scan_session_id: uuid.UUID
    accepted_version_id: uuid.UUID
    source_version_id: uuid.UUID
    asset_id: uuid.UUID

    def job_input(self) -> dict[str, object]:
        return {
            "preserve_scan_asset_id": str(self.asset_id),
            "promoted_from_scan": {
                "scan_session_id": str(self.scan_session_id),
                "accepted_version_id": str(self.accepted_version_id),
                "source_version_id": str(self.source_version_id),
                "method": PROMOTION_METHOD,
            },
        }


def _uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise FacadeScanLineageError("scan lineage contains an invalid identifier") from exc


def _is_ancestor(db: Session, *, ancestor_id: uuid.UUID, version: ProjectVersion) -> bool:
    current: ProjectVersion | None = version
    seen: set[uuid.UUID] = set()
    while current is not None and current.id not in seen:
        if current.id == ancestor_id:
            return True
        seen.add(current.id)
        current = (
            db.get(ProjectVersion, current.parent_version_id)
            if current.parent_version_id is not None
            else None
        )
    return False


def _has_asset_role(
    db: Session, *, version_id: uuid.UUID, asset_id: uuid.UUID, role: AssetRole
) -> bool:
    return (
        db.scalar(
            sa.select(VersionAsset.version_id).where(
                VersionAsset.version_id == version_id,
                VersionAsset.asset_id == asset_id,
                VersionAsset.role == role,
            )
        )
        is not None
    )


def validate_lineage(
    db: Session,
    *,
    source: ProjectVersion,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    promoted: object,
    preserve_scan_asset_id: object,
    produced: ProjectVersion | None = None,
) -> FacadeScanLineage:
    """Validate a queued or persisted promotion against the accepted scan and asset links."""
    if not isinstance(promoted, dict):
        raise FacadeScanLineageError("scan lineage is incomplete")
    scan_id = _uuid(promoted.get("scan_session_id"))
    accepted_version_id = _uuid(promoted.get("accepted_version_id"))
    original_source_id = _uuid(promoted.get("source_version_id"))
    asset_id = _uuid(preserve_scan_asset_id)
    if promoted.get("method") != PROMOTION_METHOD:
        raise FacadeScanLineageError("scan lineage method is invalid")

    project = db.get(Project, project_id)
    asset = db.get(Asset, asset_id)
    scan = db.get(ScanSession, scan_id)
    accepted = db.get(ProjectVersion, accepted_version_id)
    original_source = db.get(ProjectVersion, original_source_id)
    if (
        project is None
        or project.workspace_id != workspace_id
        or source.project_id != project_id
        or asset is None
        or asset.workspace_id != workspace_id
        or scan is None
        or scan.workspace_id != workspace_id
        or scan.project_id != project_id
        or scan.status is not ScanStatus.accepted
        or scan.result_version_id != accepted_version_id
        or scan.mesh_asset_id != asset_id
        or (scan.capabilities or {}).get("subject") != "exterior"
        or accepted is None
        or accepted.project_id != project_id
        or original_source is None
        or original_source.project_id != project_id
        or not _is_ancestor(db, ancestor_id=accepted_version_id, version=original_source)
        or not _has_asset_role(
            db, version_id=accepted_version_id, asset_id=asset_id, role=AssetRole.model
        )
    ):
        raise FacadeScanLineageError("the exterior scan is not bound to its accepted version")

    if source.id != original_source_id and not _has_asset_role(
        db, version_id=source.id, asset_id=asset_id, role=AssetRole.scan
    ):
        raise FacadeScanLineageError("the preserved scan is not bound to the source version")
    if produced is not None and (
        produced.project_id != project_id
        or produced.parent_version_id != source.id
        or not _has_asset_role(db, version_id=produced.id, asset_id=asset_id, role=AssetRole.scan)
    ):
        raise FacadeScanLineageError("the preserved scan is not bound to the produced version")
    return FacadeScanLineage(scan_id, accepted_version_id, original_source_id, asset_id)


def promotion_input(
    db: Session, *, source: ProjectVersion, scan: ScanSession, workspace_id: uuid.UUID
) -> dict[str, object]:
    """Build the first promotion payload only after validating the accepted scan binding."""
    if scan.result_version_id is None or scan.mesh_asset_id is None:
        raise FacadeScanLineageError("the exterior scan has no accepted mesh")
    lineage = FacadeScanLineage(
        scan_session_id=scan.id,
        accepted_version_id=scan.result_version_id,
        source_version_id=source.id,
        asset_id=scan.mesh_asset_id,
    )
    validate_lineage(
        db,
        source=source,
        workspace_id=workspace_id,
        project_id=source.project_id,
        promoted=lineage.job_input()["promoted_from_scan"],
        preserve_scan_asset_id=lineage.asset_id,
    )
    return lineage.job_input()


def continuity_input(
    db: Session, *, version: ProjectVersion, workspace_id: uuid.UUID
) -> dict[str, object]:
    """Recover lineage from the succeeded job that created this exact immutable version."""
    job = db.scalar(
        sa.select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == version.project_id,
            Job.type == FACADE_JOB,
            Job.status == JobStatus.succeeded,
            Job.result["version_id"].astext == str(version.id),
        )
        .limit(1)
    )
    if job is None:
        return {}
    promoted = job.input.get("promoted_from_scan")
    preserved_asset = job.input.get("preserve_scan_asset_id")
    if promoted is None and preserved_asset is None:
        return {}
    if not isinstance(promoted, dict) or preserved_asset is None:
        raise FacadeScanLineageError("facade scan lineage is incomplete")
    source_id = _uuid(job.input.get("version_id"))
    source = db.get(ProjectVersion, source_id)
    if (
        source is None
        or source.project_id != version.project_id
        or job.project_version_id != source.id
        or version.parent_version_id != source.id
    ):
        raise FacadeScanLineageError("facade scan lineage has a broken immutable parent")
    lineage = validate_lineage(
        db,
        source=source,
        produced=version,
        workspace_id=workspace_id,
        project_id=version.project_id,
        promoted=promoted,
        preserve_scan_asset_id=preserved_asset,
    )
    return lineage.job_input()
