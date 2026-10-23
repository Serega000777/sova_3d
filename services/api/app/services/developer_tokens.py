"""Self-service integration tokens for the public API (F-066)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError, ValidationFailedError
from app.auth import issue_token
from app.models.auth import ApiToken

LABEL_PREFIX = "developer:"


def create(
    db: Session, *, user_id: uuid.UUID, label: str, expires_in_days: int
) -> tuple[str, ApiToken]:
    clean = re.sub(r"\s+", " ", label.strip())
    if not clean:
        raise ValidationFailedError("developer token label must not be empty")
    token, row = issue_token(
        db,
        user_id,
        label=f"{LABEL_PREFIX}{clean}",
        ttl=timedelta(days=expires_in_days),
    )
    return token, row


def list_for(db: Session, *, user_id: uuid.UUID) -> list[ApiToken]:
    return list(
        db.scalars(
            sa.select(ApiToken)
            .where(
                ApiToken.user_id == user_id,
                ApiToken.label.startswith(LABEL_PREFIX),
            )
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
    )


def revoke(db: Session, *, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user_id or not (row.label or "").startswith(LABEL_PREFIX):
        raise NotFoundError("developer token", token_id)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.flush()


def public_label(row: ApiToken) -> str:
    label = row.label or ""
    return label.removeprefix(LABEL_PREFIX)
