"""F-068: authenticated, read-only credit catalogue and quote endpoint."""

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import PrincipalDep
from app.api.errors import ValidationFailedError
from app.services import pricing

router = APIRouter(prefix="/pricing", tags=["pricing"])


class ActionPriceOut(BaseModel):
    action_type: str
    category: pricing.PricingCategory
    credits: Decimal
    title_ru: str
    title_en: str


class PricingCatalogueOut(BaseModel):
    version: str
    charging_mode: str
    currency: str = "credit"
    actions: list[ActionPriceOut]


class PricingQuoteBody(BaseModel):
    action_type: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1, le=1000)


class PricingQuoteOut(BaseModel):
    version: str
    charging_mode: str
    action_type: str
    quantity: int
    unit_credits: Decimal
    total_credits: Decimal


def _action(row: pricing.ActionPrice) -> ActionPriceOut:
    return ActionPriceOut(
        action_type=row.action_type,
        category=row.category,
        credits=row.credits,
        title_ru=row.title_ru,
        title_en=row.title_en,
    )


@router.get("", response_model=PricingCatalogueOut)
def get_pricing(_principal: PrincipalDep) -> PricingCatalogueOut:
    return PricingCatalogueOut(
        version=pricing.PRICING_VERSION,
        charging_mode=pricing.CHARGING_MODE,
        actions=[_action(row) for row in pricing.catalogue()],
    )


@router.post("/quote", response_model=PricingQuoteOut)
def quote_price(body: PricingQuoteBody, _principal: PrincipalDep) -> PricingQuoteOut:
    try:
        row = pricing.action_price(body.action_type)
    except ValueError as exc:
        raise ValidationFailedError(
            "unknown pricing action", {"action_type": body.action_type}
        ) from exc
    return PricingQuoteOut(
        version=pricing.PRICING_VERSION,
        charging_mode=pricing.CHARGING_MODE,
        action_type=row.action_type,
        quantity=body.quantity,
        unit_credits=row.credits,
        total_credits=pricing.quote(row.action_type, body.quantity),
    )
