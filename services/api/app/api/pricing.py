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


class SubscriptionOfferOut(BaseModel):
    code: str
    monthly_price_minor: int
    included_credits: int
    seats: int
    title_ru: str
    title_en: str


class CreditPackOut(BaseModel):
    code: str
    price_minor: int
    credits: int


class MarketOffersOut(BaseModel):
    market: pricing.MarketCode
    currency: pricing.CurrencyCode
    subscriptions: list[SubscriptionOfferOut]
    credit_packs: list[CreditPackOut]


class PricingCatalogueOut(BaseModel):
    version: str
    charging_mode: str
    commercial_mode: str = "proposal"
    currency: str = "credit"
    actions: list[ActionPriceOut]
    markets: list[MarketOffersOut]


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


def _market(row: pricing.MarketOffers) -> MarketOffersOut:
    return MarketOffersOut(
        market=row.market,
        currency=row.currency,
        subscriptions=[
            SubscriptionOfferOut(
                code=offer.code,
                monthly_price_minor=offer.monthly_price_minor,
                included_credits=offer.included_credits,
                seats=offer.seats,
                title_ru=offer.title_ru,
                title_en=offer.title_en,
            )
            for offer in row.subscriptions
        ],
        credit_packs=[
            CreditPackOut(code=pack.code, price_minor=pack.price_minor, credits=pack.credits)
            for pack in row.credit_packs
        ],
    )


@router.get("", response_model=PricingCatalogueOut)
def get_pricing(_principal: PrincipalDep) -> PricingCatalogueOut:
    return PricingCatalogueOut(
        version=pricing.PRICING_VERSION,
        charging_mode=pricing.CHARGING_MODE,
        actions=[_action(row) for row in pricing.catalogue()],
        markets=[_market(row) for row in pricing.market_offers()],
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
