"""Integration fixtures backed by a real PostgreSQL.

Uses TEST_DATABASE_URL (default: the compose Postgres on 15432, database
`physicalai_test`, created on demand). Unreachable DB skips locally but fails
under CI so a broken database never passes silently.
"""

import argparse
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

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
