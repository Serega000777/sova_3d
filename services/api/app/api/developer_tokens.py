"""Developer API keys: show the secret once, persist only its hash (F-066)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep
from app.models.auth import ApiToken
from app.services import developer_tokens

router = APIRouter(prefix="/developer-tokens", tags=["developer API"])


class DeveloperTokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(default=90, ge=1, le=365)


class DeveloperTokenOut(BaseModel):
    id: uuid.UUID
    label: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def of(cls, row: ApiToken) -> "DeveloperTokenOut":
        assert row.expires_at is not None
        return cls(
            id=row.id,
            label=developer_tokens.public_label(row),
            created_at=row.created_at,
            expires_at=row.expires_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
        )


class DeveloperTokenCreated(BaseModel):
    token: str
    item: DeveloperTokenOut


@router.get("", response_model=list[DeveloperTokenOut])
def list_developer_tokens(db: DbDep, principal: PrincipalDep) -> list[DeveloperTokenOut]:
    return [
        DeveloperTokenOut.of(row)
        for row in developer_tokens.list_for(db, user_id=principal.user_id)
    ]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DeveloperTokenCreated)
def create_developer_token(
    body: DeveloperTokenCreate, db: DbDep, principal: PrincipalDep
) -> DeveloperTokenCreated:
    token, row = developer_tokens.create(
        db,
        user_id=principal.user_id,
        label=body.label,
        expires_in_days=body.expires_in_days,
    )
    return DeveloperTokenCreated(token=token, item=DeveloperTokenOut.of(row))


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_developer_token(token_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> None:
    developer_tokens.revoke(db, user_id=principal.user_id, token_id=token_id)
