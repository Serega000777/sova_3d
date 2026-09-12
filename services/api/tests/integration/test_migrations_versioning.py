"""T-008: assets / project_versions / version_assets immutability constraints."""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Asset, Project, ProjectVersion, User, VersionAsset, Workspace
from app.models.core import WorkspaceKind
from app.models.versioning import AssetKind, AssetRole, VersionState
from tests.integration.conftest import alembic_config, enum_names, table_names

VERSIONING_TABLES = {"assets", "project_versions", "version_assets"}
VERSIONING_ENUMS = {"asset_kind", "version_state", "asset_role"}
SHA_A = "a" * 64
SHA_B = "b" * 64


def test_upgrade_downgrade_0002(migrated_db: Engine, database_url: str) -> None:
    engine = migrated_db
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0001")
    assert not (VERSIONING_TABLES & table_names(engine))
    assert not (VERSIONING_ENUMS & enum_names(engine))

    command.upgrade(cfg, "0002")
    assert VERSIONING_TABLES <= table_names(engine)
    assert VERSIONING_ENUMS <= enum_names(engine)
    with engine.connect() as conn:
        triggers = {
            row[0]
            for row in conn.execute(sa.text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
        }
    assert {"assets_immutable", "project_versions_immutable", "version_assets_frozen"} <= triggers

    command.upgrade(cfg, "head")


@pytest.fixture
def project(db_session: Session) -> Project:
    user = User(email=f"{uuid.uuid4()}@example.com")
    workspace = Workspace(name="ws", kind=WorkspaceKind.personal, owner=user)
    project = Project(workspace=workspace, name="p")
    db_session.add(project)
    db_session.flush()
    return project


@pytest.fixture
def make_asset(db_session: Session, project: Project) -> Callable[[str], Asset]:
    def _make(sha: str) -> Asset:
        asset = Asset(
            workspace_id=project.workspace_id,
            kind=AssetKind.original,
            sha256=sha,
            storage_key=f"ws/{project.workspace_id}/{sha}.stl",
            mime="model/stl",
            format="stl",
            byte_size=1234,
        )
        db_session.add(asset)
        db_session.flush()
        return asset

    return _make


@contextmanager
def expect_integrity_error(session: Session, message: str) -> Iterator[None]:
    """Run the mutation inside a SAVEPOINT; the flush on exit fails and only the savepoint
    rolls back, so rows created earlier in the test survive. (begin_nested() flushes pending
    state *before* opening the savepoint, hence the mutation must happen inside the block.)"""
    with pytest.raises(sa.exc.IntegrityError) as exc_info, session.begin_nested():
        yield
    assert message in str(exc_info.value.orig)


def test_asset_binary_fields_are_immutable(
    db_session: Session, make_asset: Callable[[str], Asset]
) -> None:
    asset = make_asset(SHA_A)
    asset.metadata_ = {"triangles": 12}
    db_session.flush()  # metadata is the one mutable column

    with expect_integrity_error(db_session, "assets are immutable"):
        asset.sha256 = SHA_B


def test_asset_sha256_unique_per_workspace_and_hex(
    db_session: Session, make_asset: Callable[[str], Asset], project: Project
) -> None:
    make_asset(SHA_A)

    def derived(sha: str, key: str) -> Asset:
        return Asset(
            workspace_id=project.workspace_id,
            kind=AssetKind.derived,
            sha256=sha,
            storage_key=key,
            mime="model/stl",
            byte_size=1,
        )

    with expect_integrity_error(db_session, "uq_assets_workspace_sha256"):
        db_session.add(derived(SHA_A, "other-key"))
    with expect_integrity_error(db_session, "ck_assets_sha256_hex"):
        db_session.add(derived("not-hex", "bad-key"))


def test_finalized_version_is_immutable_and_undeletable(
    db_session: Session, project: Project
) -> None:
    v1 = ProjectVersion(project=project, sequence_no=1, label="draft")
    db_session.add(v1)
    db_session.flush()

    v1.label = "renamed while draft"
    v1.state = VersionState.finalized
    db_session.flush()
    db_session.refresh(v1)
    assert v1.finalized_at is not None

    with expect_integrity_error(db_session, "is immutable"):
        v1.label = "edit after finalize"
    with expect_integrity_error(db_session, "cannot be deleted"):
        db_session.delete(v1)


def test_draft_version_lineage_is_fixed(db_session: Session, project: Project) -> None:
    v1 = ProjectVersion(project=project, sequence_no=1)
    v2 = ProjectVersion(project=project, sequence_no=2, parent=v1)
    db_session.add_all([v1, v2])
    db_session.flush()

    with expect_integrity_error(db_session, "lineage fields are immutable"):
        v2.parent_version_id = None


def test_sequence_unique_per_project_and_head_fk(db_session: Session, project: Project) -> None:
    v1 = ProjectVersion(project=project, sequence_no=1)
    db_session.add(v1)
    db_session.flush()
    project.head_version_id = v1.id
    db_session.flush()

    with expect_integrity_error(db_session, "uq_project_versions_project_sequence"):
        db_session.add(ProjectVersion(project=project, sequence_no=1))
    with expect_integrity_error(db_session, "fk_projects_head_version_id_project_versions"):
        project.head_version_id = uuid.uuid4()


def test_version_assets_frozen_after_finalize(
    db_session: Session, project: Project, make_asset: Callable[[str], Asset]
) -> None:
    model = make_asset(SHA_A)
    preview = make_asset(SHA_B)
    v1 = ProjectVersion(project=project, sequence_no=1)
    db_session.add(v1)
    db_session.flush()
    db_session.add(VersionAsset(version_id=v1.id, asset_id=model.id, role=AssetRole.model))
    db_session.flush()

    v1.state = VersionState.finalized
    db_session.flush()

    # Regenerable roles may still be attached to a finalized version...
    db_session.add(VersionAsset(version_id=v1.id, asset_id=preview.id, role=AssetRole.preview))
    db_session.flush()

    # ...but content roles are frozen in both directions.
    with expect_integrity_error(db_session, "are frozen"):
        db_session.add(VersionAsset(version_id=v1.id, asset_id=preview.id, role=AssetRole.source))
    link = db_session.get(VersionAsset, (v1.id, model.id, AssetRole.model))
    assert link is not None
    with expect_integrity_error(db_session, "are frozen"):
        db_session.delete(link)
