"""Provider-neutral 3D generation contracts stay honest about provider capability."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.providers.colmap_3d import ColmapThreeDProvider
from app.ai.providers.shap_e_3d import ShapEThreeDProvider
from app.ai.three_d import (
    GenerationBenchmarkGroup,
    GenerationBenchmarkReport,
    GenerationMode,
    GenerationPurpose,
    GenerationRequest,
    QualityReport,
    TargetFormat,
    quality_report_from_repair,
)
from app.api.errors import ValidationFailedError
from app.services.generation import routing_evidence_from_benchmark


def _request(**overrides: object) -> GenerationRequest:
    values: dict[str, object] = {
        "mode": "text",
        "purpose": "draft",
        "prompt": "an owl figurine",
        "target_format": "stl",
    }
    values.update(overrides)
    return GenerationRequest.model_validate(values)


def test_request_requires_input_that_matches_its_mode() -> None:
    with pytest.raises(ValidationError, match="text generation requires prompt"):
        GenerationRequest.model_validate(
            {"mode": "text", "purpose": "draft", "target_format": "stl"}
        )
    with pytest.raises(ValidationError, match="2-8 images"):
        GenerationRequest.model_validate(
            {"mode": "multiview", "purpose": "standard", "target_format": "glb"}
        )


def test_shap_e_exposes_a_bounded_honest_estimate() -> None:
    provider = ShapEThreeDProvider()
    caps = provider.capabilities()
    estimate = provider.estimate(_request())

    assert caps.modes == [GenerationMode.text, GenerationMode.image]
    assert caps.purposes == [GenerationPurpose.draft, GenerationPurpose.standard]
    assert caps.formats == [TargetFormat.stl, TargetFormat.glb] and caps.self_hosted
    assert caps.max_images == 1
    assert estimate.credits == Decimal("30")
    assert estimate.cost_usd is None
    assert estimate.latency_seconds_max == 4200
    assert any("not yet converted to USD" in item for item in estimate.assumptions)


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": "game"},
        {"target_format": "obj"},
        {"pbr": True},
        {"target_triangles": 20_000},
    ],
)
def test_shap_e_refuses_capabilities_it_does_not_have(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationFailedError):
        ShapEThreeDProvider().estimate(_request(**overrides))


def test_repair_diagnostics_become_a_provider_neutral_quality_report() -> None:
    report = quality_report_from_repair(
        {
            "printable_after": False,
            "after": {
                "faces": 120,
                "vertices": 70,
                "non_manifold_edges": 2,
                "boundary_edges": 3,
                "bodies": 2,
            },
        }
    )

    assert report.triangles == 120 and report.vertices == 70
    assert report.non_manifold_edges == 2 and report.open_boundaries == 3
    assert report.disconnected_components == 2 and not report.printable
    assert report.recommended_actions == [
        "repair_non_manifold_edges",
        "close_open_boundaries",
        "review_disconnected_components",
        "run_print_repair",
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"triangles": -1},
        {"schema_version": 2},
        {"import_ok": "false"},
        {"unexpected": True},
    ],
)
def test_quality_report_rejects_malformed_benchmark_evidence(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "import_ok": True,
        "triangles": 120,
        "vertices": 70,
        "non_manifold_edges": 0,
        "open_boundaries": 0,
        "disconnected_components": 1,
        "printable": True,
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        QualityReport.model_validate(values)


def test_routing_evidence_uses_only_matching_rated_outcomes() -> None:
    report = GenerationBenchmarkReport(
        groups=[
            GenerationBenchmarkGroup(
                provider="provider-a",
                model="model-a",
                provider_version="v1",
                mode="text",
                purpose="draft",
                runs=8,
                active=0,
                succeeded=8,
                failed=0,
                cancelled=0,
                accepted=3,
                accepted_after_fix=1,
                rejected=1,
                mixed=1,
                unrated=2,
                total_cost_usd=Decimal("1"),
            ),
            GenerationBenchmarkGroup(
                provider="provider-a",
                model="model-a",
                provider_version="v2",
                mode="text",
                purpose="draft",
                runs=2,
                active=0,
                succeeded=2,
                failed=0,
                cancelled=0,
                accepted=1,
                accepted_after_fix=0,
                rejected=1,
                mixed=0,
                unrated=0,
                total_cost_usd=Decimal("1"),
            ),
            GenerationBenchmarkGroup(
                provider="provider-a",
                model="model-a",
                mode="image",
                purpose="draft",
                runs=5,
                active=0,
                succeeded=5,
                failed=0,
                cancelled=0,
                accepted=5,
                accepted_after_fix=0,
                rejected=0,
                mixed=0,
                unrated=0,
                total_cost_usd=Decimal("1"),
            ),
        ]
    )

    evidence = routing_evidence_from_benchmark(report, _request())

    assert set(evidence) == {("provider-a", "model-a")}
    assert evidence[("provider-a", "model-a")].rated_outcomes == 8
    assert evidence[("provider-a", "model-a")].accepted_outcomes == 5


def test_image_request_is_prepared_with_an_asset_id_and_multiview_stays_fail_closed() -> None:
    image_id = "8c093a57-71b0-4b06-9754-edf66043f2c9"
    request = GenerationRequest.model_validate(
        {
            "mode": "image",
            "purpose": "draft",
            "images": [{"asset_id": image_id}],
            "target_format": "glb",
        }
    )
    provider = ShapEThreeDProvider()

    assert provider.estimate(request).target_format is TargetFormat.glb
    assert provider.estimate(request).model == "image300M"
    assert provider.prepare(request).payload["image_asset_id"] == image_id
    with pytest.raises(ValidationFailedError):
        provider.estimate(
            GenerationRequest.model_validate(
                {
                    "mode": "multiview",
                    "purpose": "draft",
                    "images": [
                        {"asset_id": image_id, "view": "front"},
                        {"asset_id": "0ef0346c-eeef-4d37-b8a0-22a2c04168ee", "view": "back"},
                    ],
                    "target_format": "glb",
                }
            )
        )


def test_colmap_exposes_only_connected_object_multiview_glb() -> None:
    image_ids = [
        "8c093a57-71b0-4b06-9754-edf66043f2c9",
        "0ef0346c-eeef-4d37-b8a0-22a2c04168ee",
        "fbcb9581-c768-47af-bc4a-bdf7fc069372",
        "4a1bc673-a0be-447b-955c-bc162e42da2f",
    ]
    request = GenerationRequest.model_validate(
        {
            "mode": "multiview",
            "purpose": "standard",
            "images": [{"asset_id": item} for item in image_ids],
            "target_format": "glb",
            "size_mm": 125,
            "texture_resolution": 2048,
        }
    )
    provider = ColmapThreeDProvider()

    caps = provider.capabilities()
    assert caps.modes == [GenerationMode.multiview]
    assert caps.max_images == 8 and caps.formats == [TargetFormat.glb]
    estimate = provider.estimate(request)
    assert estimate.model == "sfm-delaunay-object"
    assert estimate.provider_version is None  # runtime image owns the honest COLMAP version
    assert any("orientation are inferred" in item for item in estimate.assumptions)
    prepared = provider.prepare(request).payload
    assert prepared["image_asset_ids"] == image_ids
    assert prepared["size_mm"] == 125
    assert provider.prepare(request).timeout_seconds == 7800


def test_colmap_rejects_too_few_views_and_unavailable_claims() -> None:
    provider = ColmapThreeDProvider()
    two_views = GenerationRequest.model_validate(
        {
            "mode": "multiview",
            "purpose": "standard",
            "images": [
                {"asset_id": "8c093a57-71b0-4b06-9754-edf66043f2c9"},
                {"asset_id": "0ef0346c-eeef-4d37-b8a0-22a2c04168ee"},
            ],
            "target_format": "glb",
        }
    )
    with pytest.raises(ValidationFailedError) as captured:
        provider.estimate(two_views)
    assert captured.value.details["unsupported"] == ["images<4"]

    four_views = GenerationRequest.model_validate(
        {
            **two_views.model_dump(mode="json"),
            "images": [
                *(image.model_dump(mode="json") for image in two_views.images),
                {"asset_id": "fbcb9581-c768-47af-bc4a-bdf7fc069372"},
                {"asset_id": "4a1bc673-a0be-447b-955c-bc162e42da2f"},
            ],
            "pbr": True,
        }
    )
    with pytest.raises(ValidationFailedError) as unsupported:
        provider.estimate(four_views)
    assert unsupported.value.details["unsupported"] == ["pbr=true"]
