"""Provider-neutral 3D generation contracts stay honest about provider capability."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.providers.shap_e_3d import ShapEThreeDProvider
from app.ai.three_d import (
    GenerationMode,
    GenerationPurpose,
    GenerationRequest,
    TargetFormat,
    quality_report_from_repair,
)
from app.api.errors import ValidationFailedError


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

    assert caps.modes == [GenerationMode.text]
    assert caps.purposes == [GenerationPurpose.draft, GenerationPurpose.standard]
    assert caps.formats == [TargetFormat.stl] and caps.self_hosted
    assert estimate.credits == Decimal("30")
    assert estimate.cost_usd is None
    assert estimate.latency_seconds_max == 4200
    assert any("not yet converted to USD" in item for item in estimate.assumptions)


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": "game"},
        {"target_format": "glb"},
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
