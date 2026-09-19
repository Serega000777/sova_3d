"""Templates and quick starts (T-125, F-070)."""

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import DbDep, PrincipalDep, SettingsDep
from app.api.schemas import JobAccepted
from app.services import templates

router = APIRouter(tags=["templates"])


class ParameterOut(BaseModel):
    id: str
    label_en: str
    label_ru: str
    default: float
    min: float
    max: float
    unit: str


class TemplateOut(BaseModel):
    id: str
    category: str
    title_en: str
    title_ru: str
    description_en: str
    description_ru: str
    prompt_en: str
    prompt_ru: str
    parameters: list[ParameterOut]
    next_steps_en: list[str]
    next_steps_ru: list[str]


class StartBody(BaseModel):
    workspace_id: uuid.UUID
    template_id: str = Field(max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en", pattern="^(en|ru)$")
    name: str | None = Field(default=None, max_length=200)


class StartedOut(BaseModel):
    project_id: uuid.UUID
    ai_request_id: uuid.UUID
    prompt: str
    job: JobAccepted


def _out(template: templates.Template) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        category=template.category,
        title_en=template.title_en,
        title_ru=template.title_ru,
        description_en=template.description_en,
        description_ru=template.description_ru,
        prompt_en=template.prompt_en,
        prompt_ru=template.prompt_ru,
        parameters=[ParameterOut(**vars(p)) for p in template.parameters],
        next_steps_en=list(template.next_steps_en),
        next_steps_ru=list(template.next_steps_ru),
    )


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(principal: PrincipalDep) -> list[TemplateOut]:
    return [_out(template) for template in templates.list_templates()]


@router.post(
    "/projects/from-template", status_code=status.HTTP_202_ACCEPTED, response_model=StartedOut
)
def start_from_template(
    body: StartBody, db: DbDep, settings: SettingsDep, principal: PrincipalDep
) -> StartedOut:
    project, request, job = templates.start_from_template(
        db,
        settings,
        user_id=principal.user_id,
        workspace_id=body.workspace_id,
        template_id=body.template_id,
        params=body.params,
        language=body.language,
        name=body.name,
    )
    return StartedOut(
        project_id=project.id,
        ai_request_id=request.id,
        prompt=request.prompt,
        job=JobAccepted(job_id=job.id, status=job.status, type=job.type),
    )
