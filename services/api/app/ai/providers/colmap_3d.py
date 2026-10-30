"""Local COLMAP bridge for provider-neutral object multi-view generation."""

from __future__ import annotations

from app.ai.three_d import (
    GenerationEstimate,
    GenerationLifecycleStatus,
    GenerationMode,
    GenerationPurpose,
    GenerationRequest,
    ProviderCapabilities,
    ProviderJob,
    TargetFormat,
)
from app.api.errors import ValidationFailedError
from app.services import pricing


class ColmapThreeDProvider:
    name = "colmap"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.name,
            model="sfm-delaunay-object",
            modes=[GenerationMode.multiview],
            purposes=[GenerationPurpose.draft, GenerationPurpose.standard],
            formats=[TargetFormat.glb],
            max_images=8,
            self_hosted=True,
        )

    def _validate(self, request: GenerationRequest) -> None:
        caps = self.capabilities()
        unsupported: list[str] = []
        if request.mode not in caps.modes:
            unsupported.append(f"mode={request.mode.value}")
        if request.purpose not in caps.purposes:
            unsupported.append(f"purpose={request.purpose.value}")
        if request.target_format not in caps.formats:
            unsupported.append(f"target_format={request.target_format.value}")
        if len(request.images) < 4:
            unsupported.append("images<4")
        if request.pbr:
            unsupported.append("pbr=true")
        if request.target_triangles is not None:
            unsupported.append("target_triangles")
        if request.texture_resolution not in {None, 1024, 2048, 4096}:
            unsupported.append("texture_resolution")
        if request.rig.value != "none":
            unsupported.append(f"rig={request.rig.value}")
        if request.print is not None:
            unsupported.append("print")
        if unsupported:
            raise ValidationFailedError(
                "the selected provider does not support this generation request",
                {"provider": self.name, "unsupported": unsupported},
            )

    def estimate(self, request: GenerationRequest) -> GenerationEstimate:
        self._validate(request)
        return GenerationEstimate(
            provider=self.name,
            model="sfm-delaunay-object",
            credits=pricing.action_price("generate_mesh").credits,
            cost_usd=None,
            latency_seconds_min=60,
            latency_seconds_max=7200,
            target_format=request.target_format,
            assumptions=[
                "four to eight overlapping photos of one stationary object",
                "size_mm supplies the maximum dimension; camera poses and orientation are inferred",
                "local COLMAP registration must form one connected camera model",
            ],
        )

    def prepare(self, request: GenerationRequest) -> ProviderJob:
        self._validate(request)
        return ProviderJob(
            status=GenerationLifecycleStatus.queued,
            payload={
                "image_asset_ids": [str(image.asset_id) for image in request.images],
                "size_mm": request.size_mm,
                "texture_resolution": request.texture_resolution or 2048,
            },
            timeout_seconds=7800,
        )
