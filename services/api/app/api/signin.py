"""Sign-in (T-162, F-083): codes to a phone or an email, Yandex ID / VK ID, the session."""

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, SettingsDep
from app.api.errors import error_response
from app.models.core import User
from app.models.signin import IdentityProvider
from app.services import signin
from app.signin_providers import OAUTH_LABELS, Channel, OAuthName

router = APIRouter(prefix="/auth", tags=["auth"])


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    phone: str | None
    display_name: str | None
    locale: str


class WorkspaceBrief(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class SessionOut(BaseModel):
    """What a client keeps: the token, who it is, where to open."""

    token: str
    expires_in_days: int
    user: UserOut
    workspace_id: uuid.UUID
    created: bool


class MethodsOut(BaseModel):
    """Which ways in this server offers, so a client shows only what works."""

    code: list[Channel]
    oauth: list[OAuthName]
    labels: dict[str, str]
    demo: bool  # codes come back in the response, OAuth is a demo consent page


class CodeRequest(BaseModel):
    channel: Channel
    address: str = Field(min_length=3, max_length=320)
    locale: str = Field(default="en", max_length=16)


class CodeStarted(BaseModel):
    challenge_id: uuid.UUID
    channel: Channel
    address: str  # normalized, as it will be stored
    expires_in_seconds: int
    delivery: str
    dev_code: str | None = None  # demo delivery only


class CodeVerify(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class OAuthStarted(BaseModel):
    provider: OAuthName
    authorize_url: str
    state: str
    demo: bool


class OAuthCallback(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=200)


class DemoSignInBody(BaseModel):
    provider: IdentityProvider
    identifier: str = Field(min_length=1, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    locale: str = Field(default="ru", max_length=16)


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceBrief]
    identities: list[dict[str, str | None]]


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        phone=user.phone,
        display_name=user.display_name,
        locale=user.locale,
    )


def _session_out(signed: signin.SignedIn, days: int) -> SessionOut:
    return SessionOut(
        token=signed.token,
        expires_in_days=days,
        user=_user_out(signed.user),
        workspace_id=signed.workspace.id,
        created=signed.created,
    )


@router.get("/methods", response_model=MethodsOut)
def methods(settings: SettingsDep) -> MethodsOut:
    return MethodsOut(
        code=["phone", "email"] if settings.signin_delivery != "none" else [],
        oauth=["yandex", "vk"] if settings.signin_oauth != "none" else [],
        labels=dict(OAUTH_LABELS),
        demo=settings.signin_delivery == "stub" or settings.signin_oauth == "stub",
    )


@router.post("/demo", response_model=SessionOut)
def demo_sign_in(body: DemoSignInBody, db: DbDep, settings: SettingsDep) -> SessionOut:
    """No-operator local entry used while SMS, email and OAuth providers are not connected."""
    signed = signin.demo_sign_in(
        db,
        settings,
        provider=body.provider,
        identifier=body.identifier,
        display_name=body.display_name,
        locale=body.locale,
    )
    return _session_out(signed, settings.signin_session_days)


@router.post("/codes", status_code=status.HTTP_202_ACCEPTED, response_model=CodeStarted)
def request_code(body: CodeRequest, db: DbDep, settings: SettingsDep) -> CodeStarted:
    started = signin.start_code(
        db, settings, channel=body.channel, address=body.address, locale=body.locale
    )
    return CodeStarted(
        challenge_id=started.challenge.id,
        channel=body.channel,
        address=started.challenge.address,
        expires_in_seconds=settings.signin_code_ttl_seconds,
        delivery=started.delivery,
        dev_code=started.dev_code,
    )


@router.post("/codes/{challenge_id}", response_model=SessionOut)
def verify_code(
    challenge_id: uuid.UUID, body: CodeVerify, db: DbDep, settings: SettingsDep, request: Request
) -> Any:
    try:
        signed = signin.finish_code(db, settings, challenge_id=challenge_id, code=body.code)
    except (signin.CodeRejectedError, signin.ChallengeGoneError) as exc:
        # a wrong code is an outcome to keep (the attempt counts), not a failed request
        return error_response(request, exc)
    return _session_out(signed, settings.signin_session_days)


@router.get("/oauth/{provider}/start", response_model=OAuthStarted)
def oauth_start(
    provider: OAuthName,
    db: DbDep,
    settings: SettingsDep,
    redirect_uri: str = Query(min_length=8, max_length=320),
    locale: str = Query(default="en", max_length=16),
) -> OAuthStarted:
    url, state = signin.start_oauth(
        db, settings, provider=provider, redirect_uri=redirect_uri, locale=locale
    )
    return OAuthStarted(
        provider=provider, authorize_url=url, state=state, demo=settings.signin_oauth == "stub"
    )


@router.post("/oauth/{provider}/callback", response_model=SessionOut)
def oauth_callback(
    provider: OAuthName, body: OAuthCallback, db: DbDep, settings: SettingsDep
) -> SessionOut:
    signed = signin.finish_oauth(db, settings, provider=provider, code=body.code, state=body.state)
    return _session_out(signed, settings.signin_session_days)


@router.get("/me", response_model=MeOut)
def me(db: DbDep, principal: PrincipalDep) -> MeOut:
    user = db.get(User, principal.user_id)
    assert user is not None
    return MeOut(
        user=_user_out(user),
        workspaces=[
            WorkspaceBrief(id=w.id, name=w.name, role=role.value)
            for w, role in signin.workspaces_of(db, user.id)
        ],
        identities=[
            {
                "provider": i.provider.value,
                "label": signin.label_for(i.provider.value),
                "subject": i.subject if i.provider.value in ("email", "phone") else None,
                "display_name": i.display_name,
            }
            for i in signin.identities_of(db, user.id)
        ],
    )


class MePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, min_length=2, max_length=16)


@router.patch("/me", response_model=UserOut)
def update_me(body: MePatch, db: DbDep, principal: PrincipalDep) -> UserOut:
    """Settings (F-083): the name shown in the top bar and the language of answers."""
    user = db.get(User, principal.user_id)
    assert user is not None
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if body.locale is not None:
        user.locale = body.locale.strip().lower()[:16]
    db.flush()
    return _user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbDep, principal: PrincipalDep) -> None:
    signin.revoke(db, principal.token_id)
