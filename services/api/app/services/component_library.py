"""Persistent user state and exact mounting models for the component catalogue."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.errors import ValidationFailedError
from app.engineering import components
from app.models.components import ComponentFavorite
from app.models.execution import Job
from app.services import modeling, projects


def require_component(component_id: str) -> components.Component:
    component = components.COMPONENTS.get(component_id)
    if component is None:
        raise ValidationFailedError("unknown component", {"component_id": component_id})
    return component


def favorite_ids(db: Session, *, user_id: uuid.UUID) -> list[str]:
    return list(
        db.scalars(
            sa.select(ComponentFavorite.component_id)
            .where(ComponentFavorite.user_id == user_id)
            .order_by(ComponentFavorite.saved_at, ComponentFavorite.component_id)
        )
    )


def add_favorite(db: Session, *, user_id: uuid.UUID, component_id: str) -> str:
    require_component(component_id)
    favorite = db.get(ComponentFavorite, (user_id, component_id))
    if favorite is None:
        db.add(ComponentFavorite(user_id=user_id, component_id=component_id))
        db.flush()
    return component_id


def remove_favorite(db: Session, *, user_id: uuid.UUID, component_id: str) -> None:
    require_component(component_id)
    favorite = db.get(ComponentFavorite, (user_id, component_id))
    if favorite is not None:
        db.delete(favorite)
        db.flush()


def create_mounting_model(
    db: Session,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    component_id: str,
    label: str | None,
    idempotency_key: str | None,
) -> tuple[Job, uuid.UUID]:
    component = require_component(component_id)
    if idempotency_key:
        existing = db.scalar(
            sa.select(Job).where(
                Job.workspace_id == workspace_id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None and existing.project_id is not None:
            return existing, existing.project_id
    project = projects.create_project(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        name=label or component.name,
        description=(
            "Bounded mounting envelope, base thickness, mounting holes and functional opening; "
            "cosmetic and unspecified product details are intentionally omitted."
        ),
    )
    job = modeling.start_with_primitive(
        db,
        user_id=user_id,
        project_id=project.id,
        plan=components.mounting_model_plan(component),
        idempotency_key=idempotency_key,
        provenance={
            "created_with": "component_library",
            "component_id": component.id,
            "model_scope": "mounting_geometry",
            "omits": ["cosmetic detail", "unspecified connectors and electronics"],
        },
    )
    return job, project.id
