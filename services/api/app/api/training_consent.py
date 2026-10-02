"""Training consent endpoints (self-learning plan, step 1).

GET is open to anyone who can see the project (so the settings screen can show the current
state to any member); PUT is owner-only (`training_consent.set_consent` enforces it).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbDep, PrincipalDep
from app.models.training_consent import ConsentAction
from app.services import training_consent

router = APIRouter(tags=["training-consent"])


class TrainingConsentOut(BaseModel):
    project_id: uuid.UUID
    enabled: bool
    updated_by: uuid.UUID | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class TrainingConsentUpdate(BaseModel):
    enabled: bool


class TrainingConsentEventOut(BaseModel):
    id: uuid.UUID
    action: ConsentAction
    changed_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _default_out(project_id: uuid.UUID) -> TrainingConsentOut:
    return TrainingConsentOut(
        project_id=project_id, enabled=False, updated_by=None, updated_at=None
    )


@router.get("/projects/{project_id}/training-consent", response_model=TrainingConsentOut)
def get_training_consent(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> TrainingConsentOut:
    record = training_consent.get_consent(db, user_id=principal.user_id, project_id=project_id)
    if record is None:
        return _default_out(project_id)
    return TrainingConsentOut.model_validate(record)


@router.put("/projects/{project_id}/training-consent", response_model=TrainingConsentOut)
def put_training_consent(
    project_id: uuid.UUID,
    body: TrainingConsentUpdate,
    db: DbDep,
    principal: PrincipalDep,
) -> TrainingConsentOut:
    record = training_consent.set_consent(
        db, user_id=principal.user_id, project_id=project_id, enabled=body.enabled
    )
    return TrainingConsentOut.model_validate(record)


@router.get(
    "/projects/{project_id}/training-consent/history",
    response_model=list[TrainingConsentEventOut],
)
def get_training_consent_history(
    project_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> list[TrainingConsentEventOut]:
    rows = training_consent.list_history(db, user_id=principal.user_id, project_id=project_id)
    return [TrainingConsentEventOut.model_validate(row) for row in rows]
