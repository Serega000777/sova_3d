"""Measured product-line economics (F-050), without fabricated demand forecasts."""

import uuid
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, PrincipalDep
from app.services import business

router = APIRouter(tags=["business"])


class BusinessPlanBody(BaseModel):
    workspace_id: uuid.UUID
    version_ids: list[uuid.UUID] = Field(min_length=1, max_length=12)
    target_margin_pct: Decimal = Field(default=Decimal("40"), ge=0, le=80)
    machine_rate_per_hour: Decimal = Field(default=Decimal("0"), ge=0, le=10000)
    labour_per_unit: Decimal = Field(default=Decimal("0"), ge=0, le=10000)
    packaging_per_unit: Decimal = Field(default=Decimal("0"), ge=0, le=10000)

    @model_validator(mode="after")
    def versions_are_unique(self) -> "BusinessPlanBody":
        if len(self.version_ids) != len(set(self.version_ids)):
            raise ValueError("version_ids must be unique")
        return self


class BusinessInstructionOut(BaseModel):
    ru: str
    en: str


class BusinessProductOut(BaseModel):
    project_id: uuid.UUID
    version_id: uuid.UUID
    title: str
    description: str
    mass_g: float
    print_time_min: float
    material_cost: Decimal
    unit_cost: Decimal
    recommended_price: Decimal
    gross_profit_per_unit: Decimal
    currency: str
    render_ready: bool
    render_asset_id: uuid.UUID | None
    analysis_id: uuid.UUID
    analysis_status: str
    printability_score: Decimal
    material_id: str | None
    printer_profile_id: uuid.UUID | None
    production_instructions: list[BusinessInstructionOut]


class BusinessPlanOut(BaseModel):
    workspace_id: uuid.UUID
    target_margin_pct: Decimal
    products: list[BusinessProductOut]
    currency: str
    demand_claimed: bool
    notes: list[str]


@router.post("/business/plan", response_model=BusinessPlanOut)
def create_business_plan(
    body: BusinessPlanBody, db: DbDep, principal: PrincipalDep
) -> BusinessPlanOut:
    return BusinessPlanOut.model_validate(
        business.create_plan(
            db,
            user_id=principal.user_id,
            workspace_id=body.workspace_id,
            version_ids=body.version_ids,
            target_margin_pct=body.target_margin_pct,
            machine_rate_per_hour=body.machine_rate_per_hour,
            labour_per_unit=body.labour_per_unit,
            packaging_per_unit=body.packaging_per_unit,
        )
    )
