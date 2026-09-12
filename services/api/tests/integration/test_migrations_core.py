"""T-007: users/workspaces/projects migrations go up and down cleanly."""

import sqlalchemy as sa
from alembic import command
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Project, User, Workspace, WorkspaceMember
from app.models.core import Units, WorkspaceKind, WorkspaceRole
from tests.integration.conftest import alembic_config, enum_names, table_names

CORE_TABLES = {"users", "workspaces", "workspace_members", "projects"}
CORE_ENUMS = {"workspace_kind", "workspace_role", "units"}


def test_upgrade_downgrade_roundtrip(engine: Engine, database_url: str) -> None:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    assert table_names(engine) <= {"alembic_version"}

    command.upgrade(cfg, "0001")
    assert CORE_TABLES <= table_names(engine)
    assert CORE_ENUMS <= enum_names(engine)

    command.downgrade(cfg, "base")
    assert table_names(engine) <= {"alembic_version"}
    assert not (CORE_ENUMS & enum_names(engine))

    # Second upgrade proves the migration is re-runnable after a downgrade.
    command.upgrade(cfg, "head")
    assert CORE_TABLES <= table_names(engine)


def test_core_models_roundtrip(db_session: Session) -> None:
    user = User(email="maker@example.com", display_name="Maker")
    workspace = Workspace(name="Personal", kind=WorkspaceKind.personal, owner=user)
    project = Project(workspace=workspace, name="Organizer")
    membership = WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.owner)
    db_session.add_all([workspace, project, membership])
    db_session.flush()
    db_session.refresh(project)

    assert project.id is not None
    assert project.units is Units.mm
    assert project.created_at is not None and project.updated_at is not None
    assert project.head_version_id is None
    assert user.locale == "en" and user.plan == "free" and user.flags == {}


def test_email_is_unique(db_session: Session) -> None:
    db_session.add_all([User(email="dup@example.com"), User(email="dup@example.com")])
    try:
        db_session.flush()
    except sa.exc.IntegrityError as exc:
        assert "uq_users_email" in str(exc.orig)
    else:
        raise AssertionError("duplicate email was accepted")
