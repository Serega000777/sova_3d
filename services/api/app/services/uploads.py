"""Upload sessions (T-012) and asset registration with hash verification (T-013).

Flow: POST /uploads -> presigned PUT to a staging key -> client uploads ->
POST /assets/complete -> server streams the staged object, verifies size,
sha256 and magic bytes, moves it to its content-addressed key and records
the immutable Asset row. Duplicates within a workspace resolve to the
existing asset.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import formats
from app.api.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFormatError,
    ValidationFailedError,
)
from app.models.core import Units, WorkspaceRole
from app.models.uploads import UploadSession, UploadStatus
from app.models.versioning import Asset, AssetKind
from app.services.authz import require_workspace_role
from app.storage import ObjectNotFoundError, ObjectStorage

UPLOAD_TTL = timedelta(minutes=30)
SNIFF_BYTES = 64


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    session: UploadSession
    url: str


def create_session(
    db: Session,
    storage: ObjectStorage,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    filename: str,
    content_type: str,
    byte_size: int,
    idempotency_key: str | None = None,
) -> PresignedUpload:
    require_workspace_role(db, user_id, workspace_id, WorkspaceRole.editor)

    if idempotency_key:
        existing = db.scalar(
            sa.select(UploadSession).where(
                UploadSession.workspace_id == workspace_id,
                UploadSession.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return PresignedUpload(existing, _presign(storage, existing))

    spec = formats.by_extension(filename)
    if spec is None or not spec.can_import:
        raise UnsupportedFormatError(
            "file type is not supported for import",
            {"filename": filename, "supported": [f.id for f in formats.importable()]},
        )
    mime_spec = formats.by_mime(content_type)
    if mime_spec is not spec:
        raise UnsupportedFormatError(
            "content type does not match the file extension",
            {"content_type": content_type, "expected": list(spec.mime_types)},
        )
    if byte_size <= 0:
        raise ValidationFailedError("byte_size must be positive")
    if byte_size > spec.max_bytes:
        raise PayloadTooLargeError(
            f"{spec.display_name} uploads are limited to {spec.max_bytes} bytes",
            {"max_bytes": spec.max_bytes, "byte_size": byte_size},
        )

    upload = UploadSession(
        workspace_id=workspace_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
        filename=filename,
        format_id=spec.id,
        content_type=content_type,
        byte_size=byte_size,
        storage_key="",  # set below once the id exists
        expires_at=datetime.now(UTC) + UPLOAD_TTL,
    )
    upload.id = uuid.uuid4()
    upload.storage_key = storage.upload_key(workspace_id, upload.id)
    db.add(upload)
    db.flush()
    return PresignedUpload(upload, _presign(storage, upload))


def _presign(storage: ObjectStorage, upload: UploadSession) -> str:
    ttl = max(int((upload.expires_at - datetime.now(UTC)).total_seconds()), 1)
    return storage.presign_put(upload.storage_key, upload.content_type, upload.byte_size, ttl)


def complete(
    db: Session,
    storage: ObjectStorage,
    *,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    sha256: str,
    units: Units | None = None,
) -> Asset:
    upload = db.get(UploadSession, upload_id)
    if upload is None:
        raise NotFoundError("upload", upload_id)
    require_workspace_role(db, user_id, upload.workspace_id, WorkspaceRole.editor)

    if upload.status is UploadStatus.completed and upload.asset_id is not None:
        asset = db.get(Asset, upload.asset_id)
        if asset is None:
            raise NotFoundError("asset", upload.asset_id)
        return asset  # idempotent retry
    if upload.status is UploadStatus.rejected:
        raise ConflictError("upload was rejected", {"reason": upload.rejection_reason})
    if upload.expires_at <= datetime.now(UTC):
        _reject(db, upload, "expired")
        raise ConflictError("upload session expired")

    try:
        info = storage.head(upload.storage_key)
    except ObjectNotFoundError:
        raise ValidationFailedError("no object was uploaded for this session") from None
    if info.byte_size != upload.byte_size:
        _reject(db, upload, "size_mismatch")
        _discard(storage, upload.storage_key)
        raise ValidationFailedError(
            "uploaded size does not match the declared size",
            {"declared": upload.byte_size, "actual": info.byte_size},
        )

    spec = formats.FORMATS[upload.format_id]
    digest = hashlib.sha256()
    head = b""
    for chunk in storage.iter_chunks(upload.storage_key):
        if len(head) < SNIFF_BYTES:
            head += chunk[: SNIFF_BYTES - len(head)]
        digest.update(chunk)
    actual_sha = digest.hexdigest()

    if actual_sha != sha256.lower():
        _reject(db, upload, "hash_mismatch")
        _discard(storage, upload.storage_key)
        raise ValidationFailedError(
            "sha256 does not match the uploaded content",
            {"declared": sha256, "actual": actual_sha},
        )
    if spec.magic and formats.sniff(head) is not spec:
        _reject(db, upload, "magic_mismatch")
        _discard(storage, upload.storage_key)
        raise UnsupportedFormatError(
            "file content does not look like the declared format",
            {"declared": spec.id, "detected": getattr(formats.sniff(head), "id", None)},
        )

    existing = db.scalar(
        sa.select(Asset).where(
            Asset.workspace_id == upload.workspace_id, Asset.sha256 == actual_sha
        )
    )
    if existing is not None:
        _discard(storage, upload.storage_key)
        asset = existing
    else:
        final_key = storage.object_key(upload.workspace_id, actual_sha, spec.extensions[0])
        storage.copy(upload.storage_key, final_key)
        _discard(storage, upload.storage_key)
        asset = Asset(
            workspace_id=upload.workspace_id,
            kind=AssetKind.original,
            sha256=actual_sha,
            storage_key=final_key,
            mime=spec.mime_types[0],
            format=spec.id,
            byte_size=info.byte_size,
            units=units,
            metadata_={"filename": upload.filename},
            created_by=user_id,
        )
        db.add(asset)
        db.flush()

    upload.status = UploadStatus.completed
    upload.asset_id = asset.id
    db.flush()
    return asset


def _reject(db: Session, upload: UploadSession, reason: str) -> None:
    upload.status = UploadStatus.rejected
    upload.rejection_reason = reason
    db.flush()


def _discard(storage: ObjectStorage, key: str) -> None:
    try:
        storage.delete(key)
    except ObjectNotFoundError:
        pass
