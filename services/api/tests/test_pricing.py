from decimal import Decimal

import pytest

import app.jobs.handlers  # noqa: F401 -- registers the production job catalogue
from app.jobs.runner import HANDLERS
from app.services import pricing


def test_every_registered_job_has_exactly_one_positive_credit_price() -> None:
    assert set(pricing.CATALOGUE) == set(HANDLERS)
    assert len(pricing.CATALOGUE) >= 30
    assert all(row.credits > 0 for row in pricing.CATALOGUE.values())


def test_quotes_are_versioned_deterministic_and_bounded() -> None:
    assert pricing.PRICING_VERSION == "2026-10-29.v1"
    assert pricing.CHARGING_MODE == "shadow"
    assert pricing.quote("generate_mesh", 2) == Decimal("60")
    assert pricing.action_price("slice_preview").credits == Decimal("1")
    with pytest.raises(ValueError, match="unpriced"):
        pricing.quote("future_unpriced_job")
    with pytest.raises(ValueError, match="between 1 and 1000"):
        pricing.quote("slice", 0)


def test_catalogue_order_is_stable_for_clients() -> None:
    rows = pricing.catalogue()
    assert rows == tuple(sorted(rows, key=lambda row: (row.category, row.action_type)))
