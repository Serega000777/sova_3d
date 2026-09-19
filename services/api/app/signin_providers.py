"""How a sign-in reaches the user: code delivery and OAuth accounts, behind adapters (F-083).

The core never knows an SMS gateway, a mail relay, Yandex ID or VK ID by name — it asks a
`CodeDelivery` to deliver a code and an `OAuthProvider` for an authorize URL and, later, for
the account behind a callback. Today two implementations exist: `none` (the method is off)
and `stub` — the code comes back in the response and the "provider" is the app's own demo
consent page. Real operators get an adapter each, selected by settings, and the settings
refuse the stubs in production.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlencode

from app.api.errors import APIError
from app.config import Settings

Channel = Literal["email", "phone"]
OAuthName = Literal["yandex", "vk"]

OAUTH_LABELS: dict[str, str] = {"yandex": "Yandex ID", "vk": "VK ID"}


class SignInNotEnabledError(APIError):
    status_code = 501
    code = "signin_not_enabled"


@dataclass(frozen=True, slots=True)
class Delivery:
    provider: str
    reference: str
    dev_code: str | None = None  # only the stub hands the code back


class CodeDelivery(Protocol):
    name: str

    def deliver(self, *, channel: Channel, address: str, code: str, locale: str) -> Delivery: ...


class NoDelivery:
    name = "none"

    def deliver(self, *, channel: Channel, address: str, code: str, locale: str) -> Delivery:
        raise SignInNotEnabledError(
            f"sign-in by {channel} is not enabled on this server", {"channel": channel}
        )


class StubDelivery:
    """Delivers nothing: the code is returned to the caller. Development only."""

    name = "stub"

    def deliver(self, *, channel: Channel, address: str, code: str, locale: str) -> Delivery:
        return Delivery(provider=self.name, reference=f"stub_{secrets.token_hex(6)}", dev_code=code)


@dataclass(frozen=True, slots=True)
class Account:
    """Who the OAuth provider says the user is."""

    subject: str  # the provider's stable account id
    display_name: str | None
    email: str | None = None
    phone: str | None = None


class OAuthProvider(Protocol):
    name: str

    def authorize_url(self, *, provider: OAuthName, state: str, redirect_uri: str) -> str: ...

    def exchange(self, *, provider: OAuthName, code: str, redirect_uri: str) -> Account: ...


class NoOAuth:
    name = "none"

    def authorize_url(self, *, provider: OAuthName, state: str, redirect_uri: str) -> str:
        raise SignInNotEnabledError(
            f"{OAUTH_LABELS[provider]} is not enabled on this server", {"provider": provider}
        )

    def exchange(self, *, provider: OAuthName, code: str, redirect_uri: str) -> Account:
        raise SignInNotEnabledError(
            f"{OAUTH_LABELS[provider]} is not enabled on this server", {"provider": provider}
        )


class StubOAuth:
    """The client's own consent page stands in for the operator: it sends the user back
    with `code = stub:<name>`, and the account id is derived from that name. Development."""

    name = "stub"

    def authorize_url(self, *, provider: OAuthName, state: str, redirect_uri: str) -> str:
        query = urlencode({"provider": provider, "state": state, "stub": "1"})
        return f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}{query}"

    def exchange(self, *, provider: OAuthName, code: str, redirect_uri: str) -> Account:
        prefix = "stub:"
        if not code.startswith(prefix) or not code[len(prefix) :].strip():
            raise APIError("the demo consent page did not return a name", {"code": code[:40]})
        name = code[len(prefix) :].strip()[:100]
        subject = "demo-" + hashlib.sha256(f"{provider}:{name.lower()}".encode()).hexdigest()[:16]
        return Account(subject=subject, display_name=name)


def delivery_for(settings: Settings) -> CodeDelivery:
    return StubDelivery() if settings.signin_delivery == "stub" else NoDelivery()


def oauth_for(settings: Settings) -> OAuthProvider:
    return StubOAuth() if settings.signin_oauth == "stub" else NoOAuth()
