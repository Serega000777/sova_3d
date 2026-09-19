"""Sign-in without tokens (T-162, F-083): a one-time code to a phone or an email, or an
OAuth account (Yandex ID, VK ID); the first sign-in creates the user and a personal
workspace, every sign-in ends in an ordinary API token the clients already speak.

Secrets never rest in the database: a challenge stores sha256(secret + its own id); codes
are six digits from `secrets`; a challenge is consumed once, expires, and locks after a few
wrong tries; an address may ask for a limited number of codes an hour.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import APIError, NotFoundError, ValidationFailedError
from app.auth import issue_token
from app.config import Settings
from app.models.auth import ApiToken
from app.models.core import User, Workspace, WorkspaceKind, WorkspaceMember, WorkspaceRole
from app.models.signin import IdentityProvider, SignInChallenge, UserIdentity
from app.signin_providers import (
    OAUTH_LABELS,
    Account,
    Channel,
    OAuthName,
    delivery_for,
    oauth_for,
)

CODE_DIGITS = 6
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class TooManyCodesError(APIError):
    status_code = 429
    code = "too_many_codes"


class CodeRejectedError(APIError):
    status_code = 400
    code = "code_rejected"


class ChallengeGoneError(APIError):
    status_code = 410
    code = "challenge_gone"


@dataclass(frozen=True, slots=True)
class Started:
    challenge: SignInChallenge
    delivery: str
    dev_code: str | None


@dataclass(frozen=True, slots=True)
class SignedIn:
    user: User
    workspace: Workspace
    token: str
    token_row: ApiToken
    created: bool  # a new user was made


# --- addresses ---------------------------------------------------------------------------------


def normalize_email(value: str) -> str:
    address = value.strip().lower()
    if not _EMAIL.match(address) or len(address) > 320:
        raise ValidationFailedError("that does not look like an email address", {"email": value})
    return address


def normalize_phone(value: str) -> str:
    """E.164 without the plus stored with it: "+7 (999) 123-45-67" → "+79991234567"."""
    digits = re.sub(r"\D", "", value)
    if value.strip().startswith("+"):
        pass
    elif len(digits) == 11 and digits[0] == "8":  # a Russian number typed the local way
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 10 <= len(digits) <= 15:
        raise ValidationFailedError("that does not look like a phone number", {"phone": value})
    return "+" + digits


def normalize(channel: Channel, address: str) -> str:
    return normalize_email(address) if channel == "email" else normalize_phone(address)


def _hash(secret: str, challenge_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{secret}:{challenge_id}".encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


# --- codes --------------------------------------------------------------------------------------


def start_code(
    db: Session, settings: Settings, *, channel: Channel, address: str, locale: str = "en"
) -> Started:
    normalized = normalize(channel, address)
    provider = IdentityProvider(channel)
    recent = db.scalar(
        sa.select(sa.func.count())
        .select_from(SignInChallenge)
        .where(
            SignInChallenge.provider == provider,
            SignInChallenge.address == normalized,
            SignInChallenge.created_at >= _now() - timedelta(hours=1),
        )
    )
    if (recent or 0) >= settings.signin_codes_per_hour:
        raise TooManyCodesError(
            "too many codes were requested for this address; try again later",
            {"retry_after_seconds": 3600},
        )
    code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
    challenge = SignInChallenge(
        id=uuid.uuid4(),
        provider=provider,
        address=normalized,
        secret_hash="",
        expires_at=_now() + timedelta(seconds=settings.signin_code_ttl_seconds),
        locale=locale[:16],
    )
    challenge.secret_hash = _hash(code, challenge.id)
    db.add(challenge)
    db.flush()
    delivered = delivery_for(settings).deliver(
        channel=channel, address=normalized, code=code, locale=locale
    )
    return Started(challenge=challenge, delivery=delivered.provider, dev_code=delivered.dev_code)


def _open_challenge(db: Session, challenge_id: uuid.UUID) -> SignInChallenge:
    challenge = db.get(SignInChallenge, challenge_id)
    if challenge is None:
        raise NotFoundError("challenge", challenge_id)
    if challenge.consumed_at is not None:
        raise ChallengeGoneError("this code was already used; ask for a new one")
    if challenge.expires_at <= _now():
        raise ChallengeGoneError("this code has expired; ask for a new one")
    return challenge


def finish_code(db: Session, settings: Settings, *, challenge_id: uuid.UUID, code: str) -> SignedIn:
    challenge = _open_challenge(db, challenge_id)
    if challenge.provider not in (IdentityProvider.email, IdentityProvider.phone):
        raise NotFoundError("challenge", challenge_id)
    candidate = re.sub(r"\D", "", code)
    if len(candidate) != CODE_DIGITS or _hash(candidate, challenge.id) != challenge.secret_hash:
        challenge.attempts += 1
        db.flush()
        left = settings.signin_max_attempts - challenge.attempts
        if left <= 0:
            challenge.consumed_at = _now()  # locked: a new code is needed
            db.flush()
            raise ChallengeGoneError("too many wrong codes; ask for a new one")
        raise CodeRejectedError("wrong code", {"attempts_left": left})
    challenge.consumed_at = _now()
    db.flush()
    provider = challenge.provider
    account = Account(
        subject=challenge.address,
        display_name=None,
        email=challenge.address if provider is IdentityProvider.email else None,
        phone=challenge.address if provider is IdentityProvider.phone else None,
    )
    return _sign_in(db, settings, provider=provider, account=account, locale=challenge.locale)


# --- OAuth --------------------------------------------------------------------------------------


def start_oauth(
    db: Session, settings: Settings, *, provider: OAuthName, redirect_uri: str, locale: str = "en"
) -> tuple[str, str]:
    """(authorize_url, state); the state is a challenge whose secret rides in the URL."""
    if not re.match(r"^https?://", redirect_uri) or len(redirect_uri) > 320:
        raise ValidationFailedError(
            "redirect_uri must be an http(s) URL", {"redirect_uri": redirect_uri}
        )
    adapter = oauth_for(settings)
    secret = secrets.token_urlsafe(24)
    challenge = SignInChallenge(
        id=uuid.uuid4(),
        provider=IdentityProvider(provider),
        address=redirect_uri,
        secret_hash="",
        expires_at=_now() + timedelta(seconds=settings.signin_code_ttl_seconds),
        locale=locale[:16],
    )
    challenge.secret_hash = _hash(secret, challenge.id)
    db.add(challenge)
    db.flush()
    state = f"{challenge.id}.{secret}"
    return adapter.authorize_url(provider=provider, state=state, redirect_uri=redirect_uri), state


def finish_oauth(
    db: Session, settings: Settings, *, provider: OAuthName, code: str, state: str
) -> SignedIn:
    challenge_id, _, secret = state.partition(".")
    try:
        parsed = uuid.UUID(challenge_id)
    except ValueError as exc:
        raise ValidationFailedError("malformed state", {"state": state[:40]}) from exc
    challenge = _open_challenge(db, parsed)
    if challenge.provider.value != provider or _hash(secret, challenge.id) != challenge.secret_hash:
        raise ChallengeGoneError("this sign-in attempt does not match; start again")
    challenge.consumed_at = _now()
    db.flush()
    account = oauth_for(settings).exchange(
        provider=provider, code=code, redirect_uri=challenge.address
    )
    return _sign_in(
        db, settings, provider=IdentityProvider(provider), account=account, locale=challenge.locale
    )


# --- the user behind an identity ---------------------------------------------------------------


def _sign_in(
    db: Session, settings: Settings, *, provider: IdentityProvider, account: Account, locale: str
) -> SignedIn:
    identity = db.scalar(
        sa.select(UserIdentity).where(
            UserIdentity.provider == provider, UserIdentity.subject == account.subject
        )
    )
    created = False
    user: User
    if identity is not None:
        user = identity.user
    else:
        # an OAuth account that carries a verified email joins that email's user
        found: User | None = None
        if account.email:
            found = db.scalar(sa.select(User).where(User.email == account.email))
        if found is None and account.phone:
            found = db.scalar(sa.select(User).where(User.phone == account.phone))
        if found is not None:
            user = found
        else:
            user = User(
                email=account.email,
                phone=account.phone,
                display_name=account.display_name,
                locale=locale[:16] if locale else "en",
            )
            db.add(user)
            db.flush()
            created = True
            name = account.display_name or account.email or account.phone or "my"
            workspace = Workspace(
                name=f"{name}'s workspace" if not _is_russian(locale) else "Моё пространство",
                kind=WorkspaceKind.personal,
                owner=user,
            )
            db.add(workspace)
            db.add(WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.owner))
            db.flush()
        identity = UserIdentity(
            user_id=user.id,
            provider=provider,
            subject=account.subject,
            display_name=account.display_name,
            profile={},
        )
        db.add(identity)
    if account.display_name and not user.display_name:
        user.display_name = account.display_name
    identity.last_used_at = _now()
    db.flush()
    workspace = personal_workspace(db, user)
    label = f"signin:{provider.value}"
    token, row = issue_token(
        db, user.id, label=label, ttl=timedelta(days=settings.signin_session_days)
    )
    return SignedIn(user=user, workspace=workspace, token=token, token_row=row, created=created)


def personal_workspace(db: Session, user: User) -> Workspace:
    """The workspace a fresh session opens on: the one the user owns, else the first joined."""
    owned = db.scalar(
        sa.select(Workspace)
        .where(Workspace.owner_user_id == user.id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    if owned is not None:
        return owned
    member = db.scalar(
        sa.select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    if member is None:  # a user without any workspace gets one now
        member = Workspace(name="Workspace", kind=WorkspaceKind.personal, owner=user)
        db.add(member)
        db.add(WorkspaceMember(workspace=member, user=user, role=WorkspaceRole.owner))
        db.flush()
    return member


def workspaces_of(db: Session, user_id: uuid.UUID) -> list[tuple[Workspace, WorkspaceRole]]:
    rows = db.execute(
        sa.select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at)
    )
    return [(workspace, role) for workspace, role in rows]


def identities_of(db: Session, user_id: uuid.UUID) -> list[UserIdentity]:
    return list(
        db.scalars(
            sa.select(UserIdentity)
            .where(UserIdentity.user_id == user_id)
            .order_by(UserIdentity.created_at)
        )
    )


def revoke(db: Session, token_id: uuid.UUID) -> None:
    row = db.get(ApiToken, token_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        db.flush()


def _is_russian(locale: str) -> bool:
    return locale.lower().startswith("ru")


def label_for(provider: str) -> str:
    return OAUTH_LABELS.get(provider, provider)
