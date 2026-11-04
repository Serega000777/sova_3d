"""Persist one exact S/M/L family by grouping three verified preview versions.

The geometry remains in ordinary immutable project versions.  The family record is stored in
their provenance before finalization, so it follows normal history and ownership transfer
without introducing a second geometry lifecycle.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.core import Project, WorkspaceRole
from app.models.execution import Job, JobStatus
from app.models.versioning import ProjectVersion, VersionState
from app.services import edits, projects
from app.services.authz import require_workspace_role

SizeLabel = Literal["S", "M", "L"]
LABELS: tuple[SizeLabel, ...] = ("S", "M", "L")
MAX_DIMENSION_MM = 10_000.0
DIMENSION_TOLERANCE_MM = 0.01


@dataclass(frozen=True, slots=True)
class SizeFamilyMemberRecord:
    label: SizeLabel
    version_id: uuid.UUID
    width_mm: float
    depth_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class SizeFamilyRecord:
    id: uuid.UUID
    project_id: uuid.UUID
    source_version_id: uuid.UUID
    selected_label: SizeLabel | None
    members: tuple[SizeFamilyMemberRecord, ...]
    created_at: datetime


def _uuid(value: object, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationFailedError(f"invalid {field}") from exc


def _positive_dimension(value: object, field: str) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError(f"invalid {field}") from exc
    if not math.isfinite(parsed) or not 0 < parsed <= MAX_DIMENSION_MM:
        raise ValidationFailedError(f"invalid {field}")
    return parsed


def _verified_member(
    db: Session, *, source: ProjectVersion, version: ProjectVersion, label: SizeLabel
) -> SizeFamilyMemberRecord:
    if version.project_id != source.project_id or version.parent_version_id != source.id:
        raise ValidationFailedError("every size-family member must be a direct child of the source")
    if version.state is not VersionState.draft:
        raise ConflictError("size-family members must still be draft preview versions")

    provenance = version.provenance or {}
    job_id = _uuid(provenance.get("job_id"), "size-family preview job id")
    job = db.get(Job, job_id)
    result = job.result if job is not None and isinstance(job.result, dict) else {}
    request = job.input if job is not None and isinstance(job.input, dict) else {}
    operations = request.get("operations")
    if (
        job is None
        or job.type != edits.EDIT_JOB
        or job.status is not JobStatus.succeeded
        or job.project_version_id != source.id
        or request.get("preview") is not True
        or str(request.get("version_id")) != str(source.id)
        or not isinstance(operations, list)
        or len(operations) != 1
        or not isinstance(operations[0], dict)
        or operations[0].get("type") != "set_dimensions"
        or result.get("preview") is not True
        or str(result.get("source_version_id")) != str(source.id)
        or str(result.get("version_id")) != str(version.id)
    ):
        raise ValidationFailedError("size-family member is not a verified set_dimensions preview")

    operation = operations[0]
    requested = (
        _positive_dimension(operation.get("width_mm"), "width_mm"),
        _positive_dimension(operation.get("depth_mm"), "depth_mm"),
        _positive_dimension(operation.get("height_mm"), "height_mm"),
    )
    bodies = result.get("bodies")
    last = bodies[-1] if isinstance(bodies, list) and bodies else None
    bbox = last.get("bbox_mm") if isinstance(last, dict) else None
    size = bbox.get("size") if isinstance(bbox, dict) else None
    if not isinstance(size, list) or len(size) != 3:
        raise ValidationFailedError("size-family preview has no measured output dimensions")
    measured = tuple(
        _positive_dimension(value, f"measured_{axis}_mm")
        for value, axis in zip(size, ("width", "depth", "height"), strict=True)
    )
    if any(
        abs(actual - expected) > DIMENSION_TOLERANCE_MM
        for actual, expected in zip(measured, requested, strict=True)
    ):
        raise ValidationFailedError("size-family preview dimensions do not match its exact request")
    return SizeFamilyMemberRecord(label, version.id, *measured)


def _record_from_payload(
    db: Session, *, project: Project, payload: dict[str, Any], created_at: datetime
) -> SizeFamilyRecord | None:
    if payload.get("schema_version") != 1:
        return None
    try:
        family_id = _uuid(payload.get("id"), "size-family id")
        source_id = _uuid(payload.get("source_version_id"), "size-family source version id")
    except ValidationFailedError:
        return None
    raw_members = payload.get("members")
    if not isinstance(raw_members, list) or len(raw_members) != 3:
        return None
    members: list[SizeFamilyMemberRecord] = []
    try:
        for expected_label, raw in zip(LABELS, raw_members, strict=True):
            if not isinstance(raw, dict) or raw.get("label") != expected_label:
                return None
            version_id = _uuid(raw.get("version_id"), "size-family member version id")
            members.append(
                SizeFamilyMemberRecord(
                    expected_label,
                    version_id,
                    _positive_dimension(raw.get("width_mm"), "width_mm"),
                    _positive_dimension(raw.get("depth_mm"), "depth_mm"),
                    _positive_dimension(raw.get("height_mm"), "height_mm"),
                )
            )
    except ValidationFailedError:
        return None
    versions = [db.get(ProjectVersion, member.version_id) for member in members]
    source = db.get(ProjectVersion, source_id)
    if (
        any(
            version is None
            or version.project_id != project.id
            or version.parent_version_id != source_id
            or version.state is not VersionState.finalized
            or (version.provenance or {}).get("size_family") != payload
            for version in versions
        )
        or source is None
        or source.project_id != project.id
        or source.state is not VersionState.finalized
    ):
        return None
    selected = next(
        (member.label for member in members if member.version_id == project.head_version_id), None
    )
    return SizeFamilyRecord(family_id, project.id, source_id, selected, tuple(members), created_at)


def list_size_families(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> list[SizeFamilyRecord]:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    rows = list(
        db.scalars(
            sa.select(ProjectVersion)
            .where(
                ProjectVersion.project_id == project.id,
                ProjectVersion.state == VersionState.finalized,
            )
            .order_by(ProjectVersion.created_at.desc(), ProjectVersion.id)
        )
    )
    found: dict[uuid.UUID, SizeFamilyRecord] = {}
    for row in rows:
        payload = (row.provenance or {}).get("size_family")
        if not isinstance(payload, dict):
            continue
        record = _record_from_payload(
            db, project=project, payload=payload, created_at=row.created_at
        )
        if record is not None and record.id not in found:
            found[record.id] = record
    return sorted(
        found.values(),
        key=lambda record: (record.selected_label is not None, record.created_at),
        reverse=True,
    )


def create_size_family(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    source_version_id: uuid.UUID,
    member_ids: dict[SizeLabel, uuid.UUID],
    selected_label: SizeLabel,
) -> SizeFamilyRecord:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    if set(member_ids) != set(LABELS) or len(set(member_ids.values())) != 3:
        raise ValidationFailedError("a size family requires unique S, M and L preview versions")
    with db.begin_nested():
        db.execute(sa.select(Project.id).where(Project.id == project.id).with_for_update())
        db.refresh(project)
        existing = next(
            (
                record
                for record in list_size_families(db, user_id=user_id, project_id=project.id)
                if record.source_version_id == source_version_id
                and {member.label: member.version_id for member in record.members} == member_ids
            ),
            None,
        )
        if existing is not None:
            return existing
        source = db.get(ProjectVersion, source_version_id)
        if source is None or source.project_id != project.id:
            raise NotFoundError("project_version", source_version_id)
        if source.state is not VersionState.finalized:
            raise ConflictError("size-family source must be finalized")
        if project.head_version_id != source.id:
            raise ConflictError("project changed while the size family was being built")

        versions = {label: db.get(ProjectVersion, member_ids[label]) for label in LABELS}
        if any(version is None for version in versions.values()):
            raise NotFoundError("size_family_member", "unknown")
        members = tuple(
            _verified_member(db, source=source, version=versions[label], label=label)  # type: ignore[arg-type]
            for label in LABELS
        )
        family_id = uuid.uuid4()
        payload = {
            "schema_version": 1,
            "id": str(family_id),
            "source_version_id": str(source.id),
            "members": [
                {
                    "label": member.label,
                    "version_id": str(member.version_id),
                    "width_mm": member.width_mm,
                    "depth_mm": member.depth_mm,
                    "height_mm": member.height_mm,
                }
                for member in members
            ],
        }
        for label in LABELS:
            version = versions[label]
            assert version is not None
            if "size_family" in (version.provenance or {}):
                raise ConflictError("preview version already belongs to a size family")
            version.provenance = {**(version.provenance or {}), "size_family": payload}
        db.flush()
        for label in LABELS:
            version = versions[label]
            assert version is not None
            projects.finalize_version(db, version)
        selected = versions[selected_label]
        assert selected is not None
        project.head_version_id = selected.id
        db.flush()
        created_at = max(version.created_at for version in versions.values() if version is not None)
    return SizeFamilyRecord(family_id, project.id, source.id, selected_label, members, created_at)


def select_size_family_member(
    db: Session,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    family_id: uuid.UUID,
    label: SizeLabel,
) -> SizeFamilyRecord:
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    with db.begin_nested():
        db.execute(sa.select(Project.id).where(Project.id == project.id).with_for_update())
        db.refresh(project)
        record = next(
            (
                item
                for item in list_size_families(db, user_id=user_id, project_id=project.id)
                if item.id == family_id
            ),
            None,
        )
        if record is None:
            raise NotFoundError("size_family", family_id)
        member = next(item for item in record.members if item.label == label)
        project.head_version_id = member.version_id
        db.flush()
    return SizeFamilyRecord(
        record.id,
        record.project_id,
        record.source_version_id,
        label,
        record.members,
        record.created_at,
    )
