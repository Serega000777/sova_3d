"""Shap-E bridge for the provider-neutral 3D generation contract."""

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


class ShapEThreeDProvider:
    name = "shap_e"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.name,
            model="text300M/image300M",
            version="50131012",
            modes=[GenerationMode.text, GenerationMode.image],
            purposes=[GenerationPurpose.draft, GenerationPurpose.standard],
            formats=[TargetFormat.stl, TargetFormat.glb],
            max_images=1,
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
        if request.pbr:
            unsupported.append("pbr=true")
        if request.target_triangles is not None:
            unsupported.append("target_triangles")
        if request.texture_resolution is not None:
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
            model=("image300M" if request.mode is GenerationMode.image else "text300M"),
            provider_version="50131012",
            credits=pricing.action_price("generate_mesh").credits,
            cost_usd=None,
            latency_seconds_min=60,
            latency_seconds_max=4200,
            target_format=request.target_format,
            assumptions=[
                "CPU-only self-hosted Shap-E; infrastructure cost is not yet converted to USD",
                "one repaired mesh draft; texture, PBR and rigging are not included",
            ],
        )

    def prepare(self, request: GenerationRequest) -> ProviderJob:
        self._validate(request)
        payload = {
            "size_mm": request.size_mm,
            "quality": request.quality,
        }
        if request.mode is GenerationMode.text:
            payload["prompt"] = request.prompt
        else:
            payload["image_asset_id"] = str(request.images[0].asset_id)
        return ProviderJob(
            status=GenerationLifecycleStatus.queued,
            payload=payload,
            timeout_seconds=4200,
        )
