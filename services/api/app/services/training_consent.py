"""Training consent (self-learning plan, step 1): off by default, owner-only, versioned.

Nothing reads `enabled` yet to build a dataset (docs/SELF_LEARNING_PLAN.md step 3 is still
unbuilt) — this only records a project owner's decision so that future work has something
honest to filter on, including the moment consent was revoked.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.core import WorkspaceRole
from app.models.training_consent import (
    ConsentAction,
    ProjectTrainingConsent,
    ProjectTrainingConsentEvent,
)
from app.services import projects
from app.services.authz import require_workspace_role


def get_consent(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectTrainingConsent | None:
    """Anyone who can see the project may see whether it opted into training."""
    projects.get_project(db, user_id=user_id, project_id=project_id)
    return db.get(ProjectTrainingConsent, project_id)


def set_consent(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID, enabled: bool
) -> ProjectTrainingConsent:
    """Only the workspace owner may grant or revoke — this is a decision about the data,
    not about editing the model."""
    project = projects.get_project(db, user_id=user_id, project_id=project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.owner)

    record = db.get(ProjectTrainingConsent, project_id)
    if record is None:
        record = ProjectTrainingConsent(project_id=project_id, enabled=False)
        db.add(record)
    record.enabled = enabled
    record.updated_by = user_id

    db.add(
        ProjectTrainingConsentEvent(
            project_id=project_id,
            action=ConsentAction.granted if enabled else ConsentAction.revoked,
            changed_by=user_id,
        )
    )
    db.flush()
    db.refresh(record)
    return record


def list_history(
    db: Session, *, user_id: uuid.UUID, project_id: uuid.UUID
) -> list[ProjectTrainingConsentEvent]:
    projects.get_project(db, user_id=user_id, project_id=project_id)
    return list(
        db.scalars(
            sa.select(ProjectTrainingConsentEvent)
            .where(ProjectTrainingConsentEvent.project_id == project_id)
            .order_by(ProjectTrainingConsentEvent.created_at.desc())
        )
    )
