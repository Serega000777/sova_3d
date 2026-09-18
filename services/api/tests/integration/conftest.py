"""Integration fixtures backed by a real PostgreSQL.

Uses TEST_DATABASE_URL (default: the compose Postgres on 15432, database
`physicalai_test`, created on demand). Unreachable DB skips locally but fails
under CI so a broken database never passes silently.
"""

import argparse
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth import issue_token
from app.config import Settings
from app.main import create_app
from app.models import User, Workspace, WorkspaceMember
from app.models.core import WorkspaceKind, WorkspaceRole
from app.storage import ObjectNotFoundError, S3Storage

API_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_URL = "postgresql+psycopg://physicalai:physicalai_dev@localhost:15432/physicalai_test"


def _ensure_database(url: sa.URL) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        ).scalar()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.cmd_opts = argparse.Namespace(x=[f"database_url={database_url}"])
    return cfg


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)
    try:
        _ensure_database(sa.make_url(url))
    except sa.exc.OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL unreachable at {url}: {exc.orig}")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_db(engine: Engine, database_url: str) -> Iterator[Engine]:
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield engine
    command.downgrade(cfg, "base")


@pytest.fixture
def db_session(migrated_db: Engine) -> Iterator[Session]:
    """Each test runs inside a transaction that is rolled back afterwards."""
    with migrated_db.connect() as conn:
        tx = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            tx.rollback()


def table_names(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def enum_names(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
        return {row[0] for row in rows}


# --- API client on top of the transactional session ---------------------------------------

DEFAULT_S3 = {
    "S3_ENDPOINT": "http://localhost:19000",
    "S3_BUCKET": "physical-ai-dev",
    "S3_ACCESS_KEY": "physicalai",
    "S3_SECRET_KEY": "physicalai_dev_secret",
}


def test_s3_settings(database_url: str) -> Settings:
    env = {key: os.environ.get(f"TEST_{key}", default) for key, default in DEFAULT_S3.items()}
    return Settings.model_validate(
        {
            "database_url": database_url,
            "redis_url": "redis://localhost:16379/1",
            **{key.lower(): value for key, value in env.items()},
        }
    )


@pytest.fixture(scope="session")
def storage(database_url: str) -> S3Storage:
    settings = test_s3_settings(database_url)
    s3 = S3Storage(settings)
    try:
        s3.head("__probe__")
    except ObjectNotFoundError:
        pass
    except EndpointConnectionError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"S3 unreachable at {settings.s3_endpoint}: {exc}")
    return s3


@pytest.fixture
def api_client(db_session: Session, storage: S3Storage, database_url: str) -> Iterator[TestClient]:
    """TestClient whose request-scoped DB session is the test's savepoint session."""
    app = create_app(test_s3_settings(database_url), storage=storage)

    def _override_db() -> Iterator[Session]:
        # Mirror production get_db: a failed request rolls back its own writes only.
        with db_session.begin_nested():
            yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as client:
        yield client


@dataclass(frozen=True, slots=True)
class Actor:
    user: User
    workspace: Workspace
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def make_actor(
    db: Session,
    role: WorkspaceRole = WorkspaceRole.owner,
    workspace: Workspace | None = None,
) -> Actor:
    """A user with a token. Pass `workspace` to add another member to an existing one."""
    user = User(email=f"{uuid.uuid4()}@example.com")
    if workspace is None:
        workspace = Workspace(name="ws", kind=WorkspaceKind.personal, owner=user)
        db.add(workspace)
    else:
        db.add(user)
    db.add(WorkspaceMember(workspace=workspace, user=user, role=role))
    db.flush()
    token, _ = issue_token(db, user.id, label="test")
    return Actor(user=user, workspace=workspace, token=token)


@pytest.fixture
def actor(db_session: Session) -> Actor:
    return make_actor(db_session)
