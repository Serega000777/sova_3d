"""T-009: operations / ai_requests / jobs tables, status enums, indexes, job state machine."""

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import AIRequest, Job, Operation, Project, ProjectVersion, User, Workspace
from app.models.core import WorkspaceKind
from app.models.execution import AIRequestStatus, JobStatus, SafetyState
from tests.integration.conftest import alembic_config, enum_names, table_names
from tests.integration.test_migrations_versioning import expect_integrity_error

EXECUTION_TABLES = {"operations", "ai_requests", "jobs", "job_artifacts"}
EXECUTION_ENUMS = {"job_status", "failure_class", "ai_request_status", "safety_state"}
EXECUTION_INDEXES = {
    "ix_jobs_status_created",
    "ix_jobs_workspace_created",
    "ix_jobs_active",
    "ix_ai_requests_workspace_created",
    "ix_operations_version_sequence",
}


def index_names(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        return {row[0] for row in rows}


def test_upgrade_downgrade_0003(migrated_db: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0002")
    assert not (EXECUTION_TABLES & table_names(migrated_db))
    assert not (EXECUTION_ENUMS & enum_names(migrated_db))

    command.upgrade(cfg, "0003")
    assert EXECUTION_TABLES <= table_names(migrated_db)
    assert EXECUTION_ENUMS <= enum_names(migrated_db)
    assert EXECUTION_INDEXES <= index_names(migrated_db)
    with migrated_db.connect() as conn:
        partial = conn.execute(
            sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_jobs_active'")
        ).scalar_one()
    assert "WHERE" in partial and "queued" in partial

    command.upgrade(cfg, "head")


@pytest.fixture
def workspace(db_session: Session) -> Workspace:
    user = User(email=f"{uuid.uuid4()}@example.com")
    workspace = Workspace(name="ws", kind=WorkspaceKind.personal, owner=user)
    db_session.add(workspace)
    db_session.flush()
    return workspace


def test_job_defaults_and_idempotency(db_session: Session, workspace: Workspace) -> None:
    job = Job(workspace=workspace, type="ai_command", idempotency_key="k1")
    db_session.add(job)
    db_session.flush()
    db_session.refresh(job)
    assert job.status is JobStatus.queued
    assert job.progress == 0 and job.attempts == 0 and job.max_attempts == 3
    assert job.input == {} and job.cost_usd == 0

    with expect_integrity_error(db_session, "uq_jobs_workspace_idempotency"):
        db_session.add(Job(workspace=workspace, type="ai_command", idempotency_key="k1"))

    # NULL keys never collide.
    db_session.add_all([Job(workspace=workspace, type="x"), Job(workspace=workspace, type="x")])
    db_session.flush()


def test_job_state_machine(db_session: Session, workspace: Workspace) -> None:
    job = Job(workspace=workspace, type="export")
    db_session.add(job)
    db_session.flush()

    with expect_integrity_error(db_session, "must run before reaching succeeded"):
        job.status = JobStatus.succeeded

    job.status = JobStatus.running
    job.progress = 40
    db_session.flush()
    db_session.refresh(job)
    assert job.started_at is not None and job.attempts == 1

    with expect_integrity_error(db_session, "progress must be monotonic"):
        job.progress = 10

    with expect_integrity_error(db_session, "ck_jobs_progress_range"):
        job.progress = 101

    job.status = JobStatus.succeeded
    db_session.flush()
    db_session.refresh(job)
    assert job.progress == 100 and job.finished_at is not None

    with expect_integrity_error(db_session, "is terminal"):
        job.status = JobStatus.running


def test_job_retry_increments_attempts(db_session: Session, workspace: Workspace) -> None:
    job = Job(workspace=workspace, type="repair")
    db_session.add(job)
    db_session.flush()
    for expected_attempts in (1, 2):
        job.status = JobStatus.running
        db_session.flush()
        db_session.refresh(job)
        assert job.attempts == expected_attempts
        job.status = JobStatus.queued  # requeue after a retryable failure
        db_session.flush()


def test_ai_request_and_operations_link(db_session: Session, workspace: Workspace) -> None:
    project = Project(workspace=workspace, name="p")
    version = ProjectVersion(project=project, sequence_no=1)
    job = Job(workspace=workspace, type="ai_command")
    db_session.add_all([project, version, job])
    db_session.flush()

    request = AIRequest(
        workspace=workspace,
        project=project,
        project_version_id=version.id,
        job_id=job.id,
        prompt="органайзер 200x100x50 с 6 секциями",
        context={"units": "mm", "target": "print"},
        provider="stub",
        model="stub-v1",
    )
    db_session.add(request)
    db_session.flush()
    db_session.refresh(request)
    assert request.status is AIRequestStatus.planning
    assert request.safety_state is SafetyState.ok
    assert request.cost_usd == 0

    op1 = Operation(
        project_version_id=version.id,
        sequence_no=1,
        operation_type="create_box",
        schema_version=1,
        params={"width_mm": 200, "depth_mm": 100, "height_mm": 50},
        ai_request_id=request.id,
    )
    db_session.add(op1)
    db_session.flush()
    db_session.refresh(op1)
    assert op1.entity_refs == []

    with expect_integrity_error(db_session, "uq_operations_version_sequence"):
        db_session.add(
            Operation(
                project_version_id=version.id,
                sequence_no=1,
                operation_type="translate",
                schema_version=1,
                params={},
            )
        )
    with expect_integrity_error(db_session, "ck_ai_requests_cost_nonnegative"):
        request.cost_usd = Decimal("-1")
