"""Bounded functional mechanism generation (F-037/F-038)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbDep, IdempotencyKey, PrincipalDep
from app.api.errors import ValidationFailedError
from app.api.schemas import JobAccepted
from app.models.core import Project, WorkspaceRole
from app.models.versioning import ProjectVersion
from app.services import animation_commands, jobs, projects, scene_animations, scenes
from app.services.authz import require_workspace_role

router = APIRouter(tags=["mechanisms"])
HINGED_LID_JOB = "build_hinged_lid"
SLIDING_LID_JOB = "build_sliding_lid"


class HingedLidBody(BaseModel):
    width_mm: float = Field(default=100, ge=40, le=500)
    depth_mm: float = Field(default=70, ge=30, le=500)
    base_height_mm: float = Field(default=18, ge=8, le=200)
    lid_thickness_mm: float = Field(default=4, ge=2, le=30)
    pin_diameter_mm: float = Field(default=4, ge=2, le=20)
    clearance_mm: float = Field(default=0.3, ge=0.1, le=1.0)
    max_angle_deg: float = Field(default=110, ge=30, le=180)

    @model_validator(mode="after")
    def hinge_fits(self) -> HingedLidBody:
        outer_radius = (
            self.pin_diameter_mm / 2 + self.clearance_mm + max(1.2, self.pin_diameter_mm * 0.3)
        )
        if self.base_height_mm < outer_radius * 1.1:
            raise ValueError("base_height_mm is too small for the requested pin and clearance")
        return self


class SlidingLidBody(BaseModel):
    """Open box with retaining guide lips and a separate lid sliding along platform +Y."""

    width_mm: float = Field(default=100, ge=40, le=500)
    depth_mm: float = Field(default=70, ge=30, le=500)
    base_height_mm: float = Field(default=30, ge=8, le=200)
    wall_mm: float = Field(default=3, ge=1.6, le=20)
    floor_mm: float = Field(default=2, ge=1, le=20)
    lid_thickness_mm: float = Field(default=3, ge=1.2, le=20)
    guide_width_mm: float = Field(default=1.5, ge=0.8, le=10)
    lip_overhang_mm: float = Field(default=2.5, ge=1, le=20)
    lip_thickness_mm: float = Field(default=1.5, ge=0.8, le=10)
    clearance_mm: float = Field(default=0.3, ge=0.1, le=1.0)
    max_travel_mm: float = Field(default=55, gt=0, le=500)

    @model_validator(mode="after")
    def guides_fit(self) -> SlidingLidBody:
        # Mirrors worker.mechanisms.sliding_lid_layout, which re-validates in the job.
        if self.floor_mm >= self.base_height_mm - 1:
            raise ValueError("floor_mm is too thick for base_height_mm")
        if self.width_mm - 2 * self.wall_mm < 5 or self.depth_mm - 2 * self.wall_mm < 5:
            raise ValueError("wall_mm leaves no usable cavity")
        if self.wall_mm - self.guide_width_mm - self.clearance_mm < 1.0:
            raise ValueError("the lid would not bear on the side walls (wall - guide - clearance)")
        if self.lip_overhang_mm - self.clearance_mm < 0.8:
            raise ValueError("lip_overhang_mm does not retain the lid past the clearance")
        if self.max_travel_mm > self.depth_mm - self.wall_mm - self.clearance_mm:
            raise ValueError("max_travel_mm exceeds the lid length")
        return self


class AnimationCommandBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=200)


class AnimationClip(BaseModel):
    schema_version: Literal[1] = 1
    kind: Literal["rigid_joint_clip"] = "rigid_joint_clip"
    joint_type: Literal["revolute", "prismatic"]
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    duration_seconds: float = Field(ge=0.1, le=60)


class AnimationCommandProposal(BaseModel):
    clip: AnimationClip
    language: str
    job_created: bool = False
    ai_used: bool = False


class AnimationCommandApply(AnimationCommandBody):
    clip: AnimationClip


class AnimationCommandApplied(BaseModel):
    version_id: uuid.UUID
    clip: AnimationClip


@router.post(
    "/models/{version_id}/mechanisms/hinged-lid",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def build_hinged_lid(
    version_id: uuid.UUID,
    body: HingedLidBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=HINGED_LID_JOB,
        input={"version_id": str(version.id), "spec": body.model_dump(mode="json")},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


@router.post(
    "/models/{version_id}/mechanisms/sliding-lid",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
)
def build_sliding_lid(
    version_id: uuid.UUID,
    body: SlidingLidBody,
    db: DbDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JobAccepted:
    version = projects.get_version(db, user_id=principal.user_id, version_id=version_id)
    project = projects.get_project(db, user_id=principal.user_id, project_id=version.project_id)
    require_workspace_role(db, principal.user_id, project.workspace_id, WorkspaceRole.editor)
    job = jobs.enqueue(
        db,
        workspace_id=project.workspace_id,
        project_id=project.id,
        project_version_id=version.id,
        job_type=SLIDING_LID_JOB,
        input={"version_id": str(version.id), "spec": body.model_dump(mode="json")},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
    )
    return JobAccepted(job_id=job.id, status=job.status, type=job.type)


def _animation_clip(
    db: DbDep, version_id: uuid.UUID, user_id: uuid.UUID, prompt: str
) -> tuple[ProjectVersion, Project, list[dict[str, Any]], AnimationClip, str]:
    version = projects.get_version(db, user_id=user_id, version_id=version_id)
    project = projects.get_project(db, user_id=user_id, project_id=version.project_id)
    require_workspace_role(db, user_id, project.workspace_id, WorkspaceRole.editor)
    resolved = scenes.resolve_scene(db, version=version, workspace_id=project.workspace_id)
    visible_ids = {
        str(node["id"])
        for node in resolved
        if node["kind"] == "object" and node["effective_visible"]
    }
    animation = scene_animations.mechanism_animation(version.provenance or {}, visible_ids)
    if animation is None:
        raise ValidationFailedError("the version has no single trusted visible mechanism")
    duration, language = animation_commands.parse_duration(prompt)
    clip = AnimationClip(
        joint_type=str(animation["kind"]),
        node_id=str(animation["node_id"]),
        duration_seconds=duration,
    )
    return version, project, resolved, clip, language


@router.post(
    "/models/{version_id}/animation-command-proposal",
    response_model=AnimationCommandProposal,
)
def propose_animation_command(
    version_id: uuid.UUID,
    body: AnimationCommandBody,
    db: DbDep,
    principal: PrincipalDep,
) -> AnimationCommandProposal:
    _version, _project, _resolved, clip, language = _animation_clip(
        db, version_id, principal.user_id, body.prompt
    )
    return AnimationCommandProposal(clip=clip, language=language)


@router.post(
    "/models/{version_id}/animation-command-apply",
    status_code=status.HTTP_201_CREATED,
    response_model=AnimationCommandApplied,
)
def apply_animation_command(
    version_id: uuid.UUID,
    body: AnimationCommandApply,
    db: DbDep,
    principal: PrincipalDep,
) -> AnimationCommandApplied:
    version, _project, _resolved, clip, _language = _animation_clip(
        db, version_id, principal.user_id, body.prompt
    )
    if body.clip != clip:
        raise ValidationFailedError("the confirmed animation clip does not match the command")
    made = scenes.create_scene_version(
        db,
        user_id=principal.user_id,
        version_id=version.id,
        nodes=scenes.stored_nodes(version),
        label=f"Animation · {clip.duration_seconds:g}s",
        operation="animation_clip",
        operation_details={**clip.model_dump(mode="json"), "source_version_id": str(version.id)},
    )
    return AnimationCommandApplied(version_id=made.id, clip=clip)
