"""Account-tier entitlements: the server-side source of truth for Free and Pro.

The web client keeps paid tools visible for discovery, but this module is the security
boundary.  A hidden button or a handcrafted API request must never unlock Pro work for a
Free account.  Billing will eventually change ``User.plan``; feature checks deliberately do
not depend on a payment-provider implementation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.api.errors import PaymentRequiredError, UnauthorizedError
from app.models.core import AccountTier, User


class Capability(StrEnum):
    advanced_operations = "advanced_operations"
    mesh_edit = "mesh_edit"
    reverse_engineering = "reverse_engineering"
    engineering = "engineering"
    fit_test = "fit_test"
    split_model = "split_model"
    cad_export = "cad_export"
    game_export = "game_export"
    history_restore = "history_restore"
    version_compare = "version_compare"


PRO_CAPABILITIES = frozenset(Capability)

# Free keeps the fast path: primitives, extrusion, transforms, exact dimensions and holes.
# These operations are the advanced CAD controls shown with a Pro lock in the clients.
PRO_OPERATION_TYPES = frozenset(
    {"boolean", "fillet", "chamfer", "shell", "linear_pattern", "circular_pattern", "mirror"}
)


class SubscriptionRequiredError(PaymentRequiredError):
    code = "pro_subscription_required"

    def __init__(self, capability: Capability, *, current_plan: str = "free") -> None:
        super().__init__(
            "this feature requires the Pro subscription",
            {
                "capability": capability.value,
                "current_plan": current_plan,
                "required_plan": "pro",
            },
        )


def normalized_tier(value: object) -> AccountTier:
    """Unknown or legacy values fail closed instead of accidentally unlocking Pro."""
    return "pro" if value == "pro" else "free"


def tier_for(db: Session, user_id: uuid.UUID) -> AccountTier:
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("account no longer exists")
    return normalized_tier(user.plan)


def allows(tier: AccountTier, capability: Capability) -> bool:
    return tier == "pro" and capability in PRO_CAPABILITIES


def require(db: Session, user_id: uuid.UUID, capability: Capability) -> AccountTier:
    tier = tier_for(db, user_id)
    if not allows(tier, capability):
        raise SubscriptionRequiredError(capability, current_plan=tier)
    return tier


def paid_operations(operations: Iterable[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            operation_type
            for operation in operations
            if (operation_type := operation.get("type")) in PRO_OPERATION_TYPES
        }
    )


def require_operations(
    db: Session, user_id: uuid.UUID, operations: Iterable[dict[str, Any]]
) -> None:
    blocked = paid_operations(operations)
    if not blocked:
        return
    tier = tier_for(db, user_id)
    if allows(tier, Capability.advanced_operations):
        return
    error = SubscriptionRequiredError(Capability.advanced_operations, current_plan=tier)
    error.details["operations"] = blocked
    raise error
