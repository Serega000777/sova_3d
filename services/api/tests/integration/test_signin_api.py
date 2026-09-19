"""E35 (F-083): a phone or an email plus a one-time code, or a Yandex ID / VK ID account,
becomes a user, a workspace and a session — without anyone pasting a token."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import hash_token
from app.models.auth import ApiToken
from app.models.core import User
from app.models.signin import SignInChallenge, UserIdentity
from app.services import signin
from tests.integration.conftest import Actor


def settings_of(api_client: TestClient) -> Any:
    return api_client.app.state.settings  # type: ignore[attr-defined]


def request_code(api_client: TestClient, channel: str, address: str, **extra: Any) -> Any:
    response = api_client.post(
        "/api/v1/auth/codes", json={"channel": channel, "address": address, **extra}
    )
    assert response.status_code == 202, response.text
    return response.json()


def sign_in(api_client: TestClient, channel: str, address: str, **extra: Any) -> Any:
    started = request_code(api_client, channel, address, **extra)
    assert started["delivery"] == "stub" and len(started["dev_code"]) == 6
    response = api_client.post(
        f"/api/v1/auth/codes/{started['challenge_id']}", json={"code": started["dev_code"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- codes ---------------------------------------------------------------------------------


def test_methods_say_what_this_server_offers(api_client: TestClient) -> None:
    methods = api_client.get("/api/v1/auth/methods").json()
    assert methods["code"] == ["phone", "email"] and methods["oauth"] == ["yandex", "vk"]
    assert methods["demo"] is True and methods["labels"]["yandex"] == "Yandex ID"


def test_a_phone_and_its_code_make_a_user_with_a_workspace(
    api_client: TestClient, db_session: Session
) -> None:
    session = sign_in(api_client, "phone", "8 (999) 123-45-67", locale="ru")
    assert session["created"] is True and session["token"].startswith("pai_")
    assert session["user"]["phone"] == "+79991234567" and session["user"]["email"] is None
    assert session["expires_in_days"] == 30
    # the token works like any other, on the workspace the sign-in opened
    headers = {"Authorization": f"Bearer {session['token']}"}
    projects = api_client.get(
        f"/api/v1/projects?workspace_id={session['workspace_id']}", headers=headers
    )
    assert projects.status_code == 200 and projects.json() == []
    me = api_client.get("/api/v1/auth/me", headers=headers).json()
    assert me["user"]["phone"] == "+79991234567"
    assert [w["role"] for w in me["workspaces"]] == ["owner"]
    assert me["workspaces"][0]["name"] == "Моё пространство"
    assert me["identities"] == [
        {"provider": "phone", "label": "phone", "subject": "+79991234567", "display_name": None}
    ]
    # the code is spent
    user = db_session.get(User, uuid.UUID(session["user"]["id"]))
    assert user is not None and user.locale == "ru"
    challenge = db_session.scalar(
        sa.select(SignInChallenge).where(SignInChallenge.address == "+79991234567")
    )
    assert challenge is not None and challenge.consumed_at is not None
    assert challenge.secret_hash != "" and not challenge.secret_hash.isdigit()  # never the code


def test_the_same_address_signs_in_to_the_same_user(api_client: TestClient) -> None:
    first = sign_in(api_client, "email", "Maker@Example.com ")
    second = sign_in(api_client, "email", "maker@example.com")
    assert first["created"] is True and second["created"] is False
    assert first["user"]["id"] == second["user"]["id"]
    assert first["workspace_id"] == second["workspace_id"]
    assert first["token"] != second["token"]  # a new session each time


def test_an_existing_cli_user_signs_in_by_their_email(api_client: TestClient, actor: Actor) -> None:
    assert actor.user.email is not None
    session = sign_in(api_client, "email", actor.user.email)
    assert session["created"] is False and session["user"]["id"] == str(actor.user.id)
    assert session["workspace_id"] == str(actor.workspace.id)


def test_wrong_codes_are_counted_and_the_challenge_locks(api_client: TestClient) -> None:
    started = request_code(api_client, "email", "careful@example.com")
    url = f"/api/v1/auth/codes/{started['challenge_id']}"
    wrong = "000000" if started["dev_code"] != "000000" else "111111"
    for left in (4, 3, 2, 1):
        response = api_client.post(url, json={"code": wrong})
        assert response.status_code == 400, response.text
        assert response.json()["error"]["details"]["attempts_left"] == left
    locked = api_client.post(url, json={"code": wrong})
    assert locked.status_code == 410 and locked.json()["error"]["code"] == "challenge_gone"
    # even the right code is refused now
    again = api_client.post(url, json={"code": started["dev_code"]})
    assert again.status_code == 410


def test_expired_and_reused_codes_are_refused(api_client: TestClient, db_session: Session) -> None:
    started = request_code(api_client, "phone", "+1 415 555 0100")
    challenge = db_session.get(SignInChallenge, uuid.UUID(started["challenge_id"]))
    assert challenge is not None
    challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    expired = api_client.post(
        f"/api/v1/auth/codes/{started['challenge_id']}", json={"code": started["dev_code"]}
    )
    assert expired.status_code == 410

    session = sign_in(api_client, "phone", "+1 415 555 0100")
    used = db_session.scalar(
        sa.select(SignInChallenge)
        .where(SignInChallenge.address == "+14155550100", SignInChallenge.consumed_at.is_not(None))
        .order_by(SignInChallenge.created_at.desc())
    )
    assert used is not None and session["user"]["phone"] == "+14155550100"
    reused = api_client.post(f"/api/v1/auth/codes/{used.id}", json={"code": "123456"})
    assert reused.status_code == 410
    missing = api_client.post(f"/api/v1/auth/codes/{uuid.uuid4()}", json={"code": "123456"})
    assert missing.status_code == 404


def test_an_address_may_only_ask_for_so_many_codes(api_client: TestClient) -> None:
    for _ in range(settings_of(api_client).signin_codes_per_hour):
        request_code(api_client, "email", "eager@example.com")
    response = api_client.post(
        "/api/v1/auth/codes", json={"channel": "email", "address": "eager@example.com"}
    )
    assert response.status_code == 429 and response.json()["error"]["code"] == "too_many_codes"


@pytest.mark.parametrize(
    ("channel", "address"),
    [("email", "not-an-email"), ("phone", "12"), ("phone", "call me maybe"), ("email", "a@b")],
)
def test_bad_addresses_are_refused_before_any_code(
    api_client: TestClient, channel: str, address: str
) -> None:
    response = api_client.post("/api/v1/auth/codes", json={"channel": channel, "address": address})
    assert response.status_code == 422, response.text


def test_delivery_off_means_501_not_a_silent_code(api_client: TestClient) -> None:
    settings = settings_of(api_client)
    api_client.app.state.settings = settings.model_copy(update={"signin_delivery": "none"})  # type: ignore[attr-defined]
    try:
        methods = api_client.get("/api/v1/auth/methods").json()
        assert methods["code"] == [] and methods["oauth"] == ["yandex", "vk"]
        response = api_client.post(
            "/api/v1/auth/codes", json={"channel": "email", "address": "off@example.com"}
        )
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "signin_not_enabled"
    finally:
        api_client.app.state.settings = settings  # type: ignore[attr-defined]


# --- OAuth ---------------------------------------------------------------------------------


def oauth_sign_in(api_client: TestClient, provider: str, name: str) -> Any:
    started = api_client.get(
        f"/api/v1/auth/oauth/{provider}/start",
        params={"redirect_uri": "http://localhost:3100/login", "locale": "ru"},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["demo"] is True and body["authorize_url"].startswith("http://localhost:3100/login?")
    assert f"state={body['state']}" in body["authorize_url"] and "stub=1" in body["authorize_url"]
    done = api_client.post(
        f"/api/v1/auth/oauth/{provider}/callback",
        json={"code": f"stub:{name}", "state": body["state"]},
    )
    assert done.status_code == 200, done.text
    return done.json()


def test_a_demo_yandex_account_signs_in_and_comes_back_to_the_same_user(
    api_client: TestClient, db_session: Session
) -> None:
    first = oauth_sign_in(api_client, "yandex", "Сергей")
    assert first["created"] is True and first["user"]["display_name"] == "Сергей"
    assert first["user"]["email"] is None and first["user"]["phone"] is None
    second = oauth_sign_in(api_client, "yandex", "сергей")  # the same account, any case
    assert second["created"] is False and second["user"]["id"] == first["user"]["id"]
    other = oauth_sign_in(api_client, "vk", "Сергей")  # VK is a different account
    assert other["user"]["id"] != first["user"]["id"]
    identities = db_session.scalars(
        sa.select(UserIdentity).where(UserIdentity.user_id == uuid.UUID(first["user"]["id"]))
    ).all()
    assert [i.provider.value for i in identities] == ["yandex"]
    assert identities[0].subject.startswith("demo-")


def test_oauth_state_must_match_the_provider_and_is_single_use(api_client: TestClient) -> None:
    started = api_client.get(
        "/api/v1/auth/oauth/vk/start", params={"redirect_uri": "http://localhost:3100/login"}
    ).json()
    crossed = api_client.post(
        "/api/v1/auth/oauth/yandex/callback", json={"code": "stub:x", "state": started["state"]}
    )
    assert crossed.status_code == 410
    forged = api_client.post(
        "/api/v1/auth/oauth/vk/callback",
        json={"code": "stub:x", "state": started["state"][:-3] + "abc"},
    )
    assert forged.status_code == 410
    ok = api_client.post(
        "/api/v1/auth/oauth/vk/callback", json={"code": "stub:x", "state": started["state"]}
    )
    assert ok.status_code == 200
    twice = api_client.post(
        "/api/v1/auth/oauth/vk/callback", json={"code": "stub:x", "state": started["state"]}
    )
    assert twice.status_code == 410
    bad_redirect = api_client.get(
        "/api/v1/auth/oauth/vk/start", params={"redirect_uri": "javascript:alert(1)"}
    )
    assert bad_redirect.status_code == 422
    unknown = api_client.get(
        "/api/v1/auth/oauth/github/start", params={"redirect_uri": "http://localhost:3100/login"}
    )
    assert unknown.status_code == 422


# --- the session -----------------------------------------------------------------------------


def test_logout_revokes_the_session_token(api_client: TestClient, db_session: Session) -> None:
    session = sign_in(api_client, "email", "leaving@example.com")
    headers = {"Authorization": f"Bearer {session['token']}"}
    assert api_client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert api_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    row = db_session.scalar(
        sa.select(ApiToken).where(ApiToken.token_hash == hash_token(session["token"]))
    )
    assert row is not None and row.revoked_at is not None and row.label == "signin:email"


def test_phone_numbers_are_normalized_the_same_way_everywhere() -> None:
    assert signin.normalize_phone("8 (999) 123-45-67") == "+79991234567"
    assert signin.normalize_phone("9991234567") == "+79991234567"
    assert signin.normalize_phone("+1 (415) 555-0100") == "+14155550100"
    assert signin.normalize_email(" Maker@Example.COM ") == "maker@example.com"
