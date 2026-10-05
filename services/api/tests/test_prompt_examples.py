"""Self-learning step 4: reviewed successful pairs become pinned few-shot examples."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.prompt_examples import (
    BUNDLE_SCHEMA_VERSION,
    load_prompt_examples,
    promote_prompt_examples,
    select_examples,
)
from app.services.training_dataset import SCHEMA_VERSION


def _plan(width: int = 40) -> dict[str, object]:
    return {
        "goal": "Make a box",
        "assumptions": [],
        "required_clarifications": [],
        "operations": [
            {
                "id": "body",
                "type": "create_box",
                "schema_version": 1,
                "width_mm": width,
                "depth_mm": 20,
                "height_mm": 8,
            }
        ],
        "validation_steps": ["bounding box"],
        "expected_outputs": ["body"],
    }


def _sample(
    key: str,
    *,
    prompt: str = "Box 40x20x8 mm",
    ratings: tuple[str, ...] = ("good",),
    status: str = "executed",
    safety: str = "ok",
    plan: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "record_type": "sample",
        "schema_version": SCHEMA_VERSION,
        "sample_type": "ai_request",
        "sample_key": key,
        "input": {"prompt": prompt, "context": {}},
        "output": {
            "provider": "anthropic",
            "model": "claude",
            "status": status,
            "safety_state": safety,
            "plan": plan or _plan(),
            "plan_errors": [],
        },
        "result": {"version_key": f"version-{key}"},
        "feedback": [{"rating": rating} for rating in ratings],
    }


def _dataset(path: Path, *samples: dict[str, object]) -> None:
    manifest = {
        "record_type": "manifest",
        "schema_version": SCHEMA_VERSION,
        "privacy": {"privacy_review_required": True},
    }
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in (manifest, *samples)),
        encoding="utf-8",
    )


def test_only_unambiguously_good_executed_safe_pairs_are_selected() -> None:
    rows = [
        _sample("good"),
        _sample("mixed", ratings=("good", "bad")),
        _sample("fixed", ratings=("fixed",)),
        _sample("planned", status="planned"),
        _sample("flagged", safety="flagged"),
        {**_sample("malformed"), "feedback": [{"rating": "good"}, "bad-row"]},
        _sample("duplicate", prompt=" box  40x20x8 MM "),
        {**_sample("reconstruction"), "sample_type": "reconstruction"},
    ]

    selected = select_examples(rows, limit=8)

    assert [example.sample_key for example in selected] == ["duplicate"]


def test_promotion_is_private_audited_and_runtime_requires_pinned_digest(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.jsonl"
    bundle = tmp_path / "prompt-examples.json"
    _dataset(candidate, _sample("b", prompt="Cylinder diameter 20 mm", plan=_plan(20)))

    summary = promote_prompt_examples(
        candidate,
        destination=bundle,
        review_reference="PRIV-2026-104",
        generated_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    payload = json.loads(bundle.read_text())

    assert summary.examples == 1
    assert summary.sha256 == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert bundle.stat().st_mode & 0o777 == 0o600
    assert payload["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert payload["privacy_review"] == {
        "completed": True,
        "reference": "PRIV-2026-104",
    }
    assert payload["source"]["sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()
    examples = load_prompt_examples(bundle, expected_sha256=summary.sha256)
    assert examples[0].prompt == "Cylinder diameter 20 mm"
    assert examples[0].output.operations[0]["type"] == "create_box"

    bundle.write_text(bundle.read_text().replace("Cylinder", "Tall cylinder"))
    with pytest.raises(ValueError, match="SHA-256"):
        load_prompt_examples(bundle, expected_sha256=summary.sha256)


def test_promotion_refuses_no_eligible_pairs_or_missing_review_reference(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.jsonl"
    _dataset(candidate, _sample("bad", ratings=("bad",)))
    with pytest.raises(ValueError, match="privacy review reference"):
        promote_prompt_examples(candidate, destination=tmp_path / "out.json", review_reference="")
    with pytest.raises(ValueError, match="no eligible"):
        promote_prompt_examples(
            candidate,
            destination=tmp_path / "out.json",
            review_reference="PRIV-1",
        )
