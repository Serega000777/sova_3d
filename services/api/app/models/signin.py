"""Sign-in without tokens (E35, F-083): who a user is on each provider, and the one-time
codes and OAuth states in flight."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey
from app.models.core import User


class IdentityProvider(enum.StrEnum):
    email = "email"
    phone = "phone"
    yandex = "yandex"
    vk = "vk"


class UserIdentity(UUIDPrimaryKey, CreatedAt, Base):
    """One way a user proves who they are: a verified address or an OAuth account."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        Index("ix_user_identities_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        Enum(IdentityProvider, name="identity_provider"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(320), nullable=False)  # address or account id
    display_name: Mapped[str | None] = mapped_column(String(200))
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class SignInChallenge(UUIDPrimaryKey, CreatedAt, Base):
    """A one-time code sent to an address, or an OAuth state waiting for its callback.
    Only a hash of the secret is stored; a challenge is consumed once or expires."""

    __tablename__ = "signin_challenges"
    __table_args__ = (Index("ix_signin_challenges_address_created", "address", "created_at"),)

    provider: Mapped[IdentityProvider] = mapped_column(
        Enum(IdentityProvider, name="identity_provider"), nullable=False
    )
    address: Mapped[str] = mapped_column(String(320), nullable=False)  # normalized; OAuth: redirect
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
