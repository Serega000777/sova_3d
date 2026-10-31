from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from worker import blender_handoff, blender_handoff_child, blender_runner, sandbox


def _report(source: Path) -> dict[str, Any]:
    script = Path(blender_handoff.__file__).with_name("blender_handoff_script.py")
    return {
        "schema_version": 1,
        "operation": "editable_scene",
        "blender_version": "4.3.3",
        "objects": 1,
        "meshes": 1,
        "materials": 1,
        "vertices": 8,
        "triangles": 12,
        "animations": 0,
        "animated_objects": [],
        "animation_paths": [],
        "animation_keyframes": 0,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "min_bounds_m": [-0.01, -0.01, -0.01],
        "max_bounds_m": [0.01, 0.01, 0.01],
        "external_refs": [],
        "scripts": [],
        "drivers": [],
        "packed": True,
        "sandbox_network_interfaces": ["lo"],
        "sandbox_uid": 65534,
        "capability_effective": "0000000000000000",
        "capability_permitted": "0000000000000000",
        "capability_ambient": "0000000000000000",
        "no_new_privileges": True,
    }


def test_package_uses_fixed_sandbox_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.blend"
    observed: dict[str, Any] = {}

    def fake_run(module: str, args: list[str], **kwargs: Any) -> sandbox.SandboxResult:
        observed.update(module=module, args=args, kwargs=kwargs)
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        (workdir / "output.blend").write_bytes(b"BLENDER-v300" + b"\0" * 32)
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(report))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = blender_handoff.package_editable_scene(source, output)

    assert result.ok and result.report is not None
    assert output.read_bytes().startswith(b"BLENDER")
    assert observed["module"] == "worker.blender_handoff_child"
    assert len(observed["args"]) == 1
    assert observed["kwargs"]["limits"].isolate_network is True
    assert observed["kwargs"]["input_path"].name == "input.glb"


def test_package_rejects_reopen_mismatch_and_removes_no_external_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.blend"

    def fake_run(_module: str, args: list[str], **_kwargs: Any) -> sandbox.SandboxResult:
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        changed = {**report, "objects": 2}
        (workdir / "output.blend").write_bytes(b"BLENDER-v300")
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(changed))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = blender_handoff.package_editable_scene(source, output)
    assert result.ok is False and result.error_code == "verification_mismatch"
    assert not output.exists()


def test_package_rejects_symlink_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.glb"
    source.write_bytes(b"glTF" + b"\0" * 32)
    output = tmp_path / "model.blend"

    def fake_run(_module: str, args: list[str], **_kwargs: Any) -> sandbox.SandboxResult:
        workdir = Path(args[0])
        report = _report(workdir / "input.glb")
        (workdir / "output.blend").symlink_to(workdir / "input.glb")
        (workdir / "report.json").write_text(json.dumps(report))
        (workdir / "verify.json").write_text(json.dumps(report))
        return sandbox.SandboxResult(ok=True, output={"ok": True})

    monkeypatch.setattr(sandbox, "run", fake_run)
    result = blender_handoff.package_editable_scene(source, output)
    assert result.ok is False and result.error_code == "output_missing"
    assert not output.exists()


def test_blender_command_is_fixed_and_network_mount_pid_isolated(tmp_path: Path) -> None:
    command = blender_handoff_child._command(tmp_path, "package")
    joined = " ".join(command)
    assert command[:2] == ["/usr/bin/unshare", "--net"]
    assert "/usr/bin/bwrap" in command
    assert "--unshare-pid" in command
    assert "--clearenv" in command
    assert "--proc /proc" in joined
    python_version = (
        f"{blender_handoff_child.sys.version_info.major}."
        f"{blender_handoff_child.sys.version_info.minor}"
    )
    assert (
        f"--ro-bind /usr/local/lib/python{python_version}/lib-dynload "
        f"/usr/lib/python{python_version}/lib-dynload"
    ) in joined
    assert "--disable-autoexec" in command
    assert "--python-exit-code" in command
    assert "/runner/blender_handoff_script.py" in command
    assert command[-2:] == ["--", "package"]
    assert "input.glb" not in joined
    assert "output.blend" not in joined


def test_child_fails_closed_before_launch_without_isolator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "input.glb").write_bytes(b"glTF")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PHYSICAL_AI_SANDBOX", "1")
    monkeypatch.setattr(blender_handoff_child, "BWRAP", tmp_path / "missing-bwrap")
    launched = False

    def forbidden(_command: list[str]) -> tuple[bool, str]:
        nonlocal launched
        launched = True
        return True, ""

    monkeypatch.setattr(blender_handoff_child, "_run", forbidden)
    assert blender_handoff_child.main([str(tmp_path)]) == 2
    assert launched is False
    assert json.loads(capsys.readouterr().out)["code"] == "isolation_unavailable"


def test_package_rejects_non_glb_and_non_blend_paths(tmp_path: Path) -> None:
    source = tmp_path / "model.obj"
    source.write_text("o model")
    assert blender_handoff.package_editable_scene(source, tmp_path / "out.blend").error_code == (
        "source_format_invalid"
    )
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glTF")
    assert blender_handoff.package_editable_scene(glb, tmp_path / "out.py").error_code == (
        "output_format_invalid"
    )


def test_parent_rejects_unsafe_child_attestation(tmp_path: Path) -> None:
    source = tmp_path / "input.glb"
    source.write_bytes(b"glTF")
    report = _report(source)
    report["sandbox_network_interfaces"] = ["eth0"]
    with pytest.raises(ValueError):
        blender_handoff.BlenderHandoffReport.model_validate(report)
    report = _report(source)
    report["capability_permitted"] = "0000000000200000"
    with pytest.raises(ValueError):
        blender_handoff.BlenderHandoffReport.model_validate(report)
    report = _report(source)
    report["no_new_privileges"] = False
    with pytest.raises(ValueError):
        blender_handoff.BlenderHandoffReport.model_validate(report)
    report = _report(source)
    report["animations"] = 1
    with pytest.raises(ValueError, match="animation evidence"):
        blender_handoff.BlenderHandoffReport.model_validate(report)


def test_package_delegates_to_configured_secretless_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input.glb"
    source.write_bytes(b"glTF")
    output = tmp_path / "output.blend"
    spool = tmp_path / "spool"
    observed: list[Path] = []

    def fake_submit(
        actual_source: Path, actual_output: Path, actual_spool: Path, *, timeout: int
    ) -> blender_handoff.BlenderHandoffOutcome:
        observed.extend((actual_source, actual_output, actual_spool))
        assert timeout == blender_handoff.BLENDER_LIMITS.wall_seconds + 30
        return blender_handoff.BlenderHandoffOutcome(ok=False, error_code="proof")

    monkeypatch.setenv("BLENDER_RUNNER_SPOOL", str(spool))
    monkeypatch.setattr(blender_runner, "submit", fake_submit)
    result = blender_handoff.package_editable_scene(source, output)
    assert result.error_code == "proof"
    assert observed == [source, output, spool]


def test_runner_claims_fixed_request_and_publishes_validated_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool = tmp_path / "spool"
    requests, processing, responses = blender_runner._directories(spool)
    for directory in (requests, processing, responses):
        directory.mkdir(parents=True)
    request = requests / ("a" * 32)
    request.mkdir()
    (request / "input.glb").write_bytes(b"glTF" + b"\0" * 32)

    def fake_package(
        source: Path, output: Path, **_kwargs: Any
    ) -> blender_handoff.BlenderHandoffOutcome:
        output.write_bytes(b"BLENDER-v300")
        return blender_handoff.BlenderHandoffOutcome(
            ok=True,
            report=blender_handoff.BlenderHandoffReport.model_validate(_report(source)),
        )

    monkeypatch.setattr(blender_runner, "_package_locally", fake_package)
    blender_runner.process_one(spool, request)
    response = responses / request.name
    assert not request.exists()
    assert not (processing / request.name).exists()
    assert (response / "output.blend").read_bytes().startswith(b"BLENDER")
    outcome = blender_handoff.BlenderHandoffOutcome.model_validate_json(
        (response / "outcome.json").read_text()
    )
    assert outcome.ok is True
