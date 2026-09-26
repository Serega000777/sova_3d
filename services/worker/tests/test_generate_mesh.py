"""F-001: text-to-mesh around Shap-E, with the sandbox faked (the real run is opt-in:
`SOVA_RUN_SHAP_E_LIVE=1 uv run pytest tests/test_reconstruct_photo_live.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import trimesh

from worker import generate_mesh, sandbox
from worker.importers.common import as_single_mesh
from worker.reconstruction import ReconstructionError


def _fake_child(tmp_path: Path, calls: list[list[str]]) -> Any:
    def run(module: str, args: list[str], **_: Any) -> sandbox.SandboxResult:
        calls.append([module, *args])
        raw = trimesh.creation.box(extents=(0.5, 1.0, 2.0))
        raw.apply_translation((-3.0, 4.0, -1.0))
        path = tmp_path / "raw.stl"
        raw.export(path)
        return sandbox.SandboxResult(
            ok=True, output={"ok": True, "mesh_path": str(path), "vertices": 8, "faces": 12}
        )

    return run


def test_a_prompt_becomes_a_grounded_mesh_of_the_asked_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sandbox, "run", _fake_child(tmp_path, calls))

    result = generate_mesh.generate_from_text("  a small\n owl   figurine ", 80.0, tmp_path / "o")

    assert calls[0][:3] == ["worker.shap_e_child", "text", "a small owl figurine"]
    assert result.prompt == "a small owl figurine" and result.warnings == ()
    mesh = as_single_mesh(trimesh.load(result.mesh_path, force="mesh"))
    assert mesh is not None
    assert max(mesh.extents) == pytest.approx(80.0, rel=1e-6)  # longest side, as asked
    assert mesh.bounds[0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)


@pytest.mark.parametrize(
    ("prompt", "code"), [("   ", "empty_prompt"), ("x" * 301, "prompt_too_long")]
)
def test_unusable_prompts_are_refused_before_the_model_runs(
    prompt: str, code: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sandbox, "run", _fake_child(tmp_path, calls))
    with pytest.raises(ReconstructionError) as caught:
        generate_mesh.generate_from_text(prompt, 50.0, tmp_path)
    assert caught.value.code == code and not calls


@pytest.mark.parametrize("size", [1.0, 5000.0])
def test_sizes_outside_what_a_printer_makes_are_refused(
    size: float, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sandbox, "run", _fake_child(tmp_path, calls))
    with pytest.raises(ReconstructionError) as caught:
        generate_mesh.generate_from_text("a vase", size, tmp_path)
    assert caught.value.code == "size_out_of_range" and not calls


def test_a_non_english_prompt_is_warned_about_not_silently_trusted() -> None:
    assert generate_mesh.prompt_warnings("сова на ветке")
    assert generate_mesh.prompt_warnings("an owl") == ()
    assert generate_mesh.prompt_warnings("сова owl") == ()  # English words are there to read
    assert generate_mesh.prompt_warnings("3D 42") == ()


def test_a_model_failure_surfaces_as_a_coded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sandbox,
        "run",
        lambda *a, **k: sandbox.SandboxResult(
            ok=False, failure=sandbox.FailureKind.resource_limit, message="out of memory"
        ),
    )
    with pytest.raises(ReconstructionError) as caught:
        generate_mesh.generate_from_text("a vase", 60.0, tmp_path)
    assert caught.value.code == "shap_e_failed" and "memory" in caught.value.message
