"""Manual parametric edits (T-055, F-061): typed operations straight to the kernel."""

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.services import edits, entitlements, projects

router = APIRouter(tags=["edits"])


class EditCreate(BaseModel):
    """Operations are validated against the same registry the planner is held to."""

    operations: list[dict[str, Any]] = Field(min_length=1, max_length=edits.MAX_EDIT_OPERATIONS)
    label: str | None = Field(default=None, max_length=200)
    # T-052: build it, but leave it a draft the user accepts or rejects.
    preview: bool = False
    # Start a new exact feature tree from these creator operations. The source version remains
    # immutable history; this is the selected mesh -> CAD bridge for imported/scanned models.
    replace_history: bool = False


class OperationStackItem(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    enabled: bool = True


class OperationStackItemOut(OperationStackItem):
    sequence_no: int
    type: str
    params: dict[str, Any]
    dependencies: list[str]


class OperationStackOut(BaseModel):
    version_id: uuid.UUID
    operations: list[OperationStackItemOut]


class OperationStackEdit(BaseModel):
    operations: list[OperationStackItem] = Field(min_length=1, max_length=256)
    label: str | None = Field(default=None, max_length=200)
    preview: bool = False


@router.get("/models/{version_id}/operation-stack", response_model=OperationStackOut)
def get_operation_stack(
    version_id: uuid.UUID, db: DbDep, principal: PrincipalDep
) -> OperationStackOut:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    stack = edits.operation_stack(db, version.id)
    if not stack:
        raise ValidationFailedError(
            "this version has no parametric history to edit", {"version_id": str(version.id)}
        )
    return OperationStackOut(
        version_id=version.id,
        operations=[
            OperationStackItemOut(
                id=str(item.operation["id"]),
                enabled=item.enabled,
                sequence_no=index,
                type=str(item.operation["type"]),
                params=item.operation,
                dependencies=[
                    str(ref)
                    for ref in (
                        item.operation.get("target"),
                        item.operation.get("tool"),
                        item.operation.get("operation"),
                    )
                    if ref
                ],
            )
            for index, item in enumerate(stack, start=1)
        ],
    )


@router.post(
    "/models/{version_id}/operation-stack",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def edit_operation_stack(
    version_id: uuid.UUID,
    body: OperationStackEdit,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    stack = edits.operation_stack(db, version.id)
    entitlements.require_operations(db, principal.user_id, [item.operation for item in stack])
    job = edits.enqueue_stack_edit(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        items=[item.model_dump(mode="json") for item in body.operations],
        label=body.label,
        preview=body.preview,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/edits",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def create_edit(
    version_id: uuid.UUID,
    body: EditCreate,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    entitlements.require_operations(db, principal.user_id, body.operations)
    job = edits.enqueue_edit(
        db,
        user_id=principal.user_id,
        version_id=version_id,
        operations=body.operations,
        label=body.label,
        preview=body.preview,
        replace_history=body.replace_history,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)
