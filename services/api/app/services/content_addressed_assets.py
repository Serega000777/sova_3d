"""Serialization for writers of workspace-scoped content-addressed assets."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.orm import Session


def lock_content_addressed_assets(
    db: Session, *, workspace_id: uuid.UUID, sha256s: Iterable[str]
) -> None:
    """Hold workspace/content locks until the outer transaction ends."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    for sha256 in sorted(set(sha256s)):
        lock_digest = hashlib.sha256(f"{workspace_id}:{sha256}".encode()).digest()
        lock_id = int.from_bytes(lock_digest[:8], "big", signed=True)
        db.execute(sa.select(sa.func.pg_advisory_xact_lock(lock_id)))
