"""T-010: usage_ledger schema is append-only and the service API aggregates it."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Job, User, Workspace
from app.models.core import WorkspaceKind
from app.models.usage import UsageEntry, UsageKind
from app.services import usage
from tests.integration.conftest import alembic_config, enum_names, table_names
from tests.integration.test_migrations_versioning import expect_integrity_error


def test_upgrade_downgrade_0004(migrated_db: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0003")
    assert "usage_ledger" not in table_names(migrated_db)
    assert "usage_kind" not in enum_names(migrated_db)
    command.upgrade(cfg, "head")
    assert "usage_ledger" in table_names(migrated_db)
    assert "usage_kind" in enum_names(migrated_db)


@pytest.fixture
def workspace(db_session: Session) -> Workspace:
    user = User(email=f"{uuid.uuid4()}@example.com")
    workspace = Workspace(name="ws", kind=WorkspaceKind.team, owner=user)
    db_session.add(workspace)
    db_session.flush()
    return workspace


def test_record_and_totals(db_session: Session, workspace: Workspace) -> None:
    job = Job(workspace=workspace, type="ai_command")
    db_session.add(job)
    db_session.flush()

    usage.record(
        db_session,
        workspace_id=workspace.id,
        kind=UsageKind.credits,
        quantity=100,
        unit="credit",
        credits_delta=100,
        metadata={"reason": "signup_grant"},
    )
    entry = usage.record(
        db_session,
        workspace_id=workspace.id,
        kind=UsageKind.ai_tokens,
        quantity=Decimal("1532"),
        unit="token",
        cost_usd=Decimal("0.004596"),
        credits_delta=Decimal("-0.5"),
        job_id=job.id,
        metadata={"provider": "stub", "model": "stub-v1"},
    )
    usage.record(
        db_session,
        workspace_id=workspace.id,
        kind=UsageKind.gpu_seconds,
        quantity=Decimal("12.25"),
        unit="second",
        cost_usd=Decimal("0.02"),
        credits_delta=Decimal("-2"),
        job_id=job.id,
    )
    db_session.refresh(entry)
    assert entry.created_at is not None and entry.metadata_["model"] == "stub-v1"

    totals = usage.workspace_totals(db_session, workspace.id)
    assert totals.entries == 3
    assert totals.cost_usd == Decimal("0.024596")
    assert totals.credits_balance == Decimal("97.5")
    assert totals.quantity_by_kind == {
        UsageKind.credits: Decimal("100"),
        UsageKind.ai_tokens: Decimal("1532"),
        UsageKind.gpu_seconds: Decimal("12.25"),
    }


def test_totals_are_workspace_scoped_and_windowed(
    db_session: Session, workspace: Workspace
) -> None:
    other_owner = User(email=f"{uuid.uuid4()}@example.com")
    other = Workspace(name="other", kind=WorkspaceKind.personal, owner=other_owner)
    db_session.add(other)
    db_session.flush()
    usage.record(db_session, workspace_id=other.id, kind=UsageKind.credits, quantity=5, unit="c")
    usage.record(
        db_session, workspace_id=workspace.id, kind=UsageKind.credits, quantity=1, unit="c"
    )

    assert usage.workspace_totals(db_session, workspace.id).entries == 1
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    empty = usage.workspace_totals(db_session, workspace.id, since=tomorrow)
    assert empty.entries == 0 and empty.cost_usd == 0 and empty.quantity_by_kind == {}


def test_ledger_is_append_only(db_session: Session, workspace: Workspace) -> None:
    entry = usage.record(
        db_session, workspace_id=workspace.id, kind=UsageKind.credits, quantity=1, unit="c"
    )
    with expect_integrity_error(db_session, "append-only"):
        entry.quantity = Decimal("999")
    with expect_integrity_error(db_session, "append-only"):
        db_session.delete(entry)
    assert db_session.get(UsageEntry, entry.id) is not None


def test_record_rejects_negative_quantities(db_session: Session, workspace: Workspace) -> None:
    with pytest.raises(ValueError):
        usage.record(
            db_session, workspace_id=workspace.id, kind=UsageKind.credits, quantity=-1, unit="c"
        )
    with expect_integrity_error(db_session, "ck_usage_ledger_cost_nonnegative"):
        db_session.add(
            UsageEntry(
                workspace_id=workspace.id,
                kind=UsageKind.credits,
                quantity=1,
                unit="c",
                cost_usd=Decimal("-1"),
            )
        )
