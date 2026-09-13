"""FastAPI dependencies: settings, DB session, storage, current principal."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import UnauthorizedError
from app.auth import Principal, authenticate
from app.config import Settings
from app.storage import ObjectStorage


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.storage
    return storage


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
DbDep = Annotated[Session, Depends(get_db)]


def get_principal(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("missing bearer token")
    principal = authenticate(db, token.strip())
    if principal is None:
        raise UnauthorizedError("invalid or expired token")
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]

IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=128, description="Retry-safe key")
]
