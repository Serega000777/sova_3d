"""Bearer API-token authentication.

Tokens are random 32-byte secrets shown once; only sha256(token) is stored.
An OIDC verifier can be added next to `authenticate` later — callers only
see a `Principal`.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.auth import ApiToken

TOKEN_PREFIX = "pai_"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    token_id: uuid.UUID


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(
    session: Session,
    user_id: uuid.UUID,
    *,
    label: str | None = None,
    ttl: timedelta | None = None,
) -> tuple[str, ApiToken]:
    """Create a token for a user. Returns (plaintext, row); plaintext is never stored."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        user_id=user_id,
        token_hash=hash_token(plaintext),
        label=label,
        expires_at=(datetime.now(UTC) + ttl) if ttl else None,
    )
    session.add(row)
    session.flush()
    return plaintext, row


def authenticate(session: Session, token: str) -> Principal | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    row = session.scalar(sa.select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
        return None
    row.last_used_at = datetime.now(UTC)
    return Principal(user_id=row.user_id, token_id=row.id)
