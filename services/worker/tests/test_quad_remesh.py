from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from worker import blender_runner, quad_remesh, quad_remesh_child, sandbox


def _report(source: Path, target_faces: int = 2000) -> dict[str, Any]:
    script = Path(quad_remesh.__file__).with_name("quad_remesh_script.py")
    return {
        "schema_version": 2,
        "operation": "quad_remesh",
        "blender_version": "4.3.3",
        "target_faces": target_faces,
        "faces": 1980,
        "quad_faces": 1900,
        "triangle_faces": 80,
        "other_faces": 0,
        "vertices": 2010,
        "quad_ratio": 0.9596,
        "source_uv_layers": 0,
        "uv_layers": 0,
        "uv_coordinates": 0,
        "uv_bounds": None,
        "uv_transfer": "none",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "sandbox_network_interfaces": ["lo"],
        "sandbox_uid": 65534,
        "capability_effective": "0000000000000000",
        "capability_permitted": "0000000000000000",
        "capability_ambient": "0000000000000000",
        "no_new_privileges": True,
    }


def test_remesh_uses_fixed_sandbox_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.fbx"
    observed: dict[str, Any] = {}

    def fake_run(module: str, args: list[str], **kwargs: Any) -> sandbox.SandboxResult:
        observed.update(module=module, args=args, kwargs=kwargs)
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        (workdir / "output.fbx").write_bytes(b"Kaydara FBX Binary" + b"\0" * 32)
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(report))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = quad_remesh.remesh_quads(source, output, 2000)

    assert result.ok and result.report is not None
    assert output.read_bytes().startswith(b"Kaydara")
    assert observed["module"] == "worker.quad_remesh_child"
    assert observed["args"][1] == "2000"
    assert observed["kwargs"]["limits"].isolate_network is True
    assert observed["kwargs"]["input_path"].name == "input.glb"


def test_remesh_rejects_reopen_mismatch_and_removes_no_external_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.fbx"

    def fake_run(_module: str, args: list[str], **_kwargs: Any) -> sandbox.SandboxResult:
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        changed = {**report, "faces": 1979}
        (workdir / "output.fbx").write_bytes(b"Kaydara FBX Binary")
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(changed))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = quad_remesh.remesh_quads(source, output, 2000)
    assert result.ok is False and result.error_code == "verification_mismatch"
    assert not output.exists()


def test_remesh_rejects_symlink_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.fbx"

    def fake_run(_module: str, args: list[str], **_kwargs: Any) -> sandbox.SandboxResult:
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        (workdir / "output.fbx").symlink_to(workdir / "input.glb")
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(report))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = quad_remesh.remesh_quads(source, output, 2000)
    assert result.ok is False and result.error_code == "output_missing"
    assert not output.exists()


def test_quad_remesh_command_is_fixed_and_network_mount_pid_isolated(tmp_path: Path) -> None:
    command = quad_remesh_child._command(tmp_path, "remesh", 2000)
    joined = " ".join(command)
    assert command[:2] == ["/usr/bin/unshare", "--net"]
    assert "/usr/bin/bwrap" in command
    assert "--unshare-pid" in command
    assert "--clearenv" in command
    assert "--proc /proc" in joined
    assert "--disable-autoexec" in command
    assert "--python-exit-code" in command
    assert "/runner/quad_remesh_script.py" in command
    assert command[-3:] == ["--", "remesh", "2000"]
    assert "input.glb" not in joined
    assert "output.fbx" not in joined


def test_child_rejects_out_of_bounds_target_faces_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "input.glb").write_bytes(b"glTF")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PHYSICAL_AI_SANDBOX", "1")
    launched = False

    def forbidden(_command: list[str], _timeout: float) -> tuple[bool, str]:
        nonlocal launched
        launched = True
        return True, ""

    monkeypatch.setattr(quad_remesh_child, "_run", forbidden)
    assert quad_remesh_child.main([str(tmp_path), "999999999"]) == 2
    assert launched is False
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_target_faces"


def test_child_fails_closed_before_launch_without_isolator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "input.glb").write_bytes(b"glTF")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PHYSICAL_AI_SANDBOX", "1")
    monkeypatch.setattr(quad_remesh_child, "BWRAP", tmp_path / "missing-bwrap")
    launched = False

    def forbidden(_command: list[str], _timeout: float) -> tuple[bool, str]:
        nonlocal launched
        launched = True
        return True, ""

    monkeypatch.setattr(quad_remesh_child, "_run", forbidden)
    assert quad_remesh_child.main([str(tmp_path), "2000"]) == 2
    assert launched is False
    assert json.loads(capsys.readouterr().out)["code"] == "isolation_unavailable"


def test_remesh_rejects_non_glb_and_non_fbx_paths(tmp_path: Path) -> None:
    source = tmp_path / "model.obj"
    source.write_text("o model")
    assert quad_remesh.remesh_quads(source, tmp_path / "out.fbx", 2000).error_code == (
        "source_format_invalid"
    )
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glTF")
    assert quad_remesh.remesh_quads(glb, tmp_path / "out.blend", 2000).error_code == (
        "output_format_invalid"
    )


def test_remesh_rejects_out_of_bounds_target_faces(tmp_path: Path) -> None:
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glTF")
    assert quad_remesh.remesh_quads(glb, tmp_path / "out.fbx", 50).error_code == (
        "target_faces_invalid"
    )
    assert quad_remesh.remesh_quads(glb, tmp_path / "out.fbx", 1_000_000).error_code == (
        "target_faces_invalid"
    )


def test_parent_rejects_unsafe_child_attestation(tmp_path: Path) -> None:
    source = tmp_path / "input.glb"
    source.write_bytes(b"glTF")
    report = _report(source)
    report["sandbox_network_interfaces"] = ["eth0"]
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)
    report = _report(source)
    report["capability_permitted"] = "0000000000200000"
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)
    report = _report(source)
    report["no_new_privileges"] = False
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)
    report = _report(source)
    report["target_faces"] = 1_000_000
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)
    report = _report(source)
    report.update(
        source_uv_layers=1,
        uv_layers=0,
        uv_coordinates=0,
        uv_bounds=None,
        uv_transfer="none",
    )
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)
    report = _report(source)
    report.update(uv_layers=1, uv_coordinates=4, uv_bounds=[0.0, 0.0, 1.0, 1.0])
    with pytest.raises(ValueError):
        quad_remesh.QuadRemeshReport.model_validate(report)


def test_remesh_delegates_to_configured_secretless_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input.glb"
    source.write_bytes(b"glTF")
    output = tmp_path / "output.fbx"
    spool = tmp_path / "spool"
    observed: list[Any] = []

    def fake_submit(
        actual_source: Path,
        actual_output: Path,
        actual_target_faces: int,
        actual_spool: Path,
        *,
        timeout: int,
    ) -> quad_remesh.QuadRemeshOutcome:
        observed.extend((actual_source, actual_output, actual_target_faces, actual_spool))
        assert timeout == quad_remesh.QUAD_REMESH_LIMITS.wall_seconds + 30
        return quad_remesh.QuadRemeshOutcome(ok=False, error_code="proof")

    monkeypatch.setenv("BLENDER_RUNNER_SPOOL", str(spool))
    monkeypatch.setattr(blender_runner, "submit_quad_remesh", fake_submit)
    result = quad_remesh.remesh_quads(source, output, 2000)
    assert result.error_code == "proof"
    assert observed == [source, output, 2000, spool]


def test_runner_claims_fixed_quad_remesh_request_and_publishes_validated_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool = tmp_path / "spool"
    requests, processing, responses = blender_runner._directories(spool)
    for directory in (requests, processing, responses):
        directory.mkdir(parents=True)
    request = requests / ("b" * 32)
    request.mkdir()
    (request / "input.glb").write_bytes(b"glTF" + b"\0" * 32)
    (request / "target_faces").write_text("2000", encoding="ascii")

    def fake_remesh_locally(
        source: Path, output: Path, target_faces: int, **_kwargs: Any
    ) -> quad_remesh.QuadRemeshOutcome:
        output.write_bytes(b"Kaydara FBX Binary")
        return quad_remesh.QuadRemeshOutcome(
            ok=True,
            report=quad_remesh.QuadRemeshReport.model_validate(_report(source, target_faces)),
        )

    monkeypatch.setattr(blender_runner, "_remesh_locally", fake_remesh_locally)
    blender_runner.process_one(spool, request)
    response = responses / request.name
    assert not request.exists()
    assert not (processing / request.name).exists()
    assert (response / "output.fbx").read_bytes().startswith(b"Kaydara")
    outcome = quad_remesh.QuadRemeshOutcome.model_validate_json(
        (response / "outcome.json").read_text()
    )
    assert outcome.ok is True


def test_runner_rejects_quad_remesh_request_with_bad_target_faces(tmp_path: Path) -> None:
    spool = tmp_path / "spool"
    requests, processing, responses = blender_runner._directories(spool)
    for directory in (requests, processing, responses):
        directory.mkdir(parents=True)
    request = requests / ("c" * 32)
    request.mkdir()
    (request / "input.glb").write_bytes(b"glTF" + b"\0" * 32)
    (request / "target_faces").write_text("not-a-number", encoding="ascii")

    blender_runner.process_one(spool, request)
    response = responses / request.name
    outcome = quad_remesh.QuadRemeshOutcome.model_validate_json(
        (response / "outcome.json").read_text()
    )
    assert outcome.ok is False
    assert outcome.error_code == "runner_request_invalid"
