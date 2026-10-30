"""Provider-neutral contracts for generated 3D assets.

These contracts describe user intent and observable provider behaviour.  Provider-specific
model names and payloads stay behind ``ThreeDProvider`` so clients never depend on them.
"""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationMode(enum.StrEnum):
    text = "text"
    image = "image"
    multiview = "multiview"
    retexture = "retexture"
    print = "print"


class GenerationPurpose(enum.StrEnum):
    draft = "draft"
    standard = "standard"
    game = "game"
    hero = "hero"
    print = "print"
    character = "character"


class TargetFormat(enum.StrEnum):
    glb = "glb"
    fbx = "fbx"
    obj = "obj"
    stl = "stl"
    three_mf = "3mf"
    usdz = "usdz"


class RigMode(enum.StrEnum):
    none = "none"
    humanoid = "humanoid"
    quadruped = "quadruped"


class GenerationLifecycleStatus(enum.StrEnum):
    queued = "queued"
    preprocessing = "preprocessing"
    generating_geometry = "generating_geometry"
    generating_texture = "generating_texture"
    postprocessing = "postprocessing"
    validating = "validating"
    ready = "ready"
    failed_retryable = "failed_retryable"
    failed_final = "failed_final"
    cancelled = "cancelled"


class GenerationImage(BaseModel):
    asset_id: uuid.UUID
    view: str | None = Field(default=None, max_length=32)

    model_config = ConfigDict(extra="forbid")


class PrintIntent(BaseModel):
    watertight: bool = True
    split: bool = False
    connectors: bool = False
    multicolor: bool = False

    model_config = ConfigDict(extra="forbid")


class GenerationPrivacy(BaseModel):
    """User consent boundaries that external provider routes must respect."""

    contains_personal_data: bool = False
    allow_external_processing: bool = False
    allow_provider_retention: bool = False
    allow_training: bool = False

    model_config = ConfigDict(extra="forbid")


class GenerationRequest(BaseModel):
    mode: GenerationMode
    purpose: GenerationPurpose
    prompt: str | None = Field(default=None, min_length=1, max_length=300)
    images: list[GenerationImage] = Field(default_factory=list, max_length=8)
    source_model_asset_id: uuid.UUID | None = None
    target_format: TargetFormat = TargetFormat.glb
    target_triangles: int | None = Field(default=None, ge=100, le=2_000_000)
    texture_resolution: int | None = Field(default=None)
    pbr: bool = False
    rig: RigMode = RigMode.none
    print: PrintIntent | None = None
    privacy: GenerationPrivacy = Field(default_factory=GenerationPrivacy)
    budget_usd: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=4)
    max_latency_seconds: int | None = Field(default=None, ge=1, le=86_400)
    size_mm: float = Field(default=60.0, ge=5, le=1000)
    quality: str = Field(default="fast", pattern=r"^(fast|quality)$")

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def input_matches_mode(self) -> GenerationRequest:
        if self.texture_resolution not in {None, 1024, 2048, 4096, 8192}:
            raise ValueError("texture_resolution must be 1024, 2048, 4096 or 8192")
        if self.mode is GenerationMode.text:
            if not self.prompt:
                raise ValueError("text generation requires prompt")
            if self.images or self.source_model_asset_id is not None:
                raise ValueError("text generation accepts prompt only")
        elif self.mode is GenerationMode.image:
            if len(self.images) != 1:
                raise ValueError("image generation requires exactly one image")
        elif self.mode is GenerationMode.multiview:
            if not 2 <= len(self.images) <= 8:
                raise ValueError("multiview generation requires 2-8 images")
        elif self.mode is GenerationMode.retexture:
            if self.source_model_asset_id is None:
                raise ValueError("retexture requires source_model_asset_id")
        elif self.mode is GenerationMode.print:
            if self.source_model_asset_id is None or self.print is None:
                raise ValueError("print preparation requires a source model and print options")
        if len({image.asset_id for image in self.images}) != len(self.images):
            raise ValueError("generation images must be distinct assets")
        if self.purpose is GenerationPurpose.print and self.print is None:
            raise ValueError("print purpose requires print options")
        if self.rig is not RigMode.none and self.purpose is not GenerationPurpose.character:
            raise ValueError("rigging is available only for character purpose")
        return self


class ProviderCapabilities(BaseModel):
    provider: str
    model: str
    version: str | None = None
    modes: list[GenerationMode]
    purposes: list[GenerationPurpose]
    formats: list[TargetFormat]
    max_images: int = 0
    supports_pbr: bool = False
    supports_rigging: bool = False
    supports_target_triangles: bool = False
    self_hosted: bool = False

    model_config = ConfigDict(extra="forbid")


class GenerationEstimate(BaseModel):
    provider: str
    model: str
    provider_version: str | None = None
    credits: Decimal | None = None
    cost_usd: Decimal | None = None
    latency_seconds_min: int
    latency_seconds_max: int
    target_format: TargetFormat
    assumptions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ProviderJob(BaseModel):
    provider_job_id: str | None = None
    status: GenerationLifecycleStatus
    payload: dict[str, Any] = Field(default_factory=dict)


class QualityScores(BaseModel):
    geometry: float | None = Field(default=None, ge=0, le=1)
    topology: float | None = Field(default=None, ge=0, le=1)
    texture: float | None = Field(default=None, ge=0, le=1)
    reference_alignment: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid", strict=True)


class QualityReport(BaseModel):
    schema_version: Literal[1] = 1
    import_ok: bool
    triangles: int = Field(ge=0)
    vertices: int = Field(ge=0)
    materials: int = Field(default=0, ge=0)
    texture_max: int | None = Field(default=None, ge=0)
    has_pbr: bool = False
    has_uv: bool = False
    non_manifold_edges: int = Field(ge=0)
    open_boundaries: int = Field(ge=0)
    disconnected_components: int = Field(ge=0)
    rig_valid: bool = False
    printable: bool
    scores: QualityScores = Field(default_factory=QualityScores)
    recommended_actions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderResult(BaseModel):
    raw_asset_id: uuid.UUID | None = None
    normalized_asset_id: uuid.UUID | None = None
    quality_report: QualityReport | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkQualitySummary(BaseModel):
    valid_reports: int = 0
    invalid_reports: int = 0
    average_triangles: float | None = None
    average_geometry: float | None = None
    average_topology: float | None = None
    average_texture: float | None = None
    average_reference_alignment: float | None = None


class GenerationBenchmarkGroup(BaseModel):
    provider: str
    model: str
    provider_version: str | None = None
    mode: GenerationMode
    purpose: GenerationPurpose
    runs: int
    active: int
    succeeded: int
    failed: int
    cancelled: int
    accepted: int
    accepted_after_fix: int
    rejected: int
    mixed: int
    unrated: int
    total_cost_usd: Decimal
    observed_cost_per_accepted_asset_usd: Decimal | None = None
    average_latency_seconds: float | None = None
    quality: BenchmarkQualitySummary = Field(default_factory=BenchmarkQualitySummary)


class GenerationBenchmarkReport(BaseModel):
    groups: list[GenerationBenchmarkGroup] = Field(default_factory=list)
    manual_time_included: bool = False
    cost_definition: str = (
        "terminal generation job cost divided by accepted plus accepted-after-fix assets"
    )


class ThreeDProvider(Protocol):
    """Minimal provider boundary used by the API router and future external adapters."""

    name: str

    def capabilities(self) -> ProviderCapabilities: ...

    def estimate(self, request: GenerationRequest) -> GenerationEstimate: ...

    def prepare(self, request: GenerationRequest) -> ProviderJob: ...


def quality_report_from_repair(report: dict[str, Any]) -> QualityReport:
    raw_after = report.get("after")
    after: dict[str, Any] = raw_after if isinstance(raw_after, dict) else {}
    actions: list[str] = []
    if int(after.get("non_manifold_edges", 0)):
        actions.append("repair_non_manifold_edges")
    if int(after.get("boundary_edges", 0)):
        actions.append("close_open_boundaries")
    if int(after.get("bodies", 0)) > 1:
        actions.append("review_disconnected_components")
    if not bool(report.get("printable_after", False)):
        actions.append("run_print_repair")
    return QualityReport(
        import_ok=True,
        triangles=int(after.get("faces", 0)),
        vertices=int(after.get("vertices", 0)),
        non_manifold_edges=int(after.get("non_manifold_edges", 0)),
        open_boundaries=int(after.get("boundary_edges", 0)),
        disconnected_components=int(after.get("bodies", 0)),
        printable=bool(report.get("printable_after", False)),
        recommended_actions=actions,
    )
