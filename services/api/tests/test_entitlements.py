"""Free/Pro capability matrix is deny-by-default and stable without a database."""

import pytest

from app.services import entitlements


@pytest.mark.parametrize("capability", list(entitlements.Capability))
def test_every_paid_capability_requires_pro(capability: entitlements.Capability) -> None:
    assert not entitlements.allows("free", capability)
    assert entitlements.allows("pro", capability)


def test_unknown_tiers_fail_closed() -> None:
    assert entitlements.normalized_tier(None) == "free"
    assert entitlements.normalized_tier("profi") == "free"
    assert entitlements.normalized_tier("enterprise") == "free"
    assert entitlements.normalized_tier("pro") == "pro"


def test_only_advanced_operations_are_paid() -> None:
    operations = [
        {"type": "create_box"},
        {"type": "translate"},
        {"type": "add_hole"},
        {"type": "boolean"},
        {"type": "fillet"},
        {"type": "mirror"},
        {"type": "nurbs_surface"},
    ]
    assert entitlements.paid_operations(operations) == [
        "boolean",
        "fillet",
        "mirror",
        "nurbs_surface",
    ]
