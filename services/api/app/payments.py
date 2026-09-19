"""Payment providers behind one small interface (F-004).

The marketplace records what a listing costs; how it is paid is an adapter, so the core is
never tied to one processor (constitution §2). Two providers exist today: `none` — priced
listings cannot be acquired yet, the economics pack schedules real payments after the core
product — and `stub`, which completes an order without charging, for development and demos
and refused in production by the settings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.api.errors import APIError
from app.config import Settings


class PaymentsNotEnabledError(APIError):
    status_code = 402
    code = "payments_not_enabled"


@dataclass(frozen=True, slots=True)
class Charge:
    provider: str
    reference: str
    status: str  # completed | pending


class PaymentProvider(Protocol):
    name: str

    def charge(self, *, amount_cents: int, currency: str, description: str) -> Charge: ...


class NoPayments:
    name = "none"

    def charge(self, *, amount_cents: int, currency: str, description: str) -> Charge:
        raise PaymentsNotEnabledError(
            "priced listings cannot be bought yet — payments open after the core product",
            {"amount_cents": amount_cents, "currency": currency},
        )


class StubPayments:
    """Completes every charge without moving money. Development only."""

    name = "stub"

    def charge(self, *, amount_cents: int, currency: str, description: str) -> Charge:
        return Charge(
            provider=self.name, reference=f"stub_{uuid.uuid4().hex[:12]}", status="completed"
        )


def provider_for(settings: Settings) -> PaymentProvider:
    if settings.payments_provider == "stub":
        return StubPayments()
    return NoPayments()
