"""Fixed-operation Blender packaging for validated Sova geometry.

The public entrypoint accepts only a GLB produced by Sova's validated exporter.  Blender runs as
a descendant of the existing scrubbed worker sandbox with auto-execution disabled; callers cannot
provide Python, add-ons, shell fragments, command-line switches, or filesystem destinations.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from worker import sandbox


class BlenderHandoffReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: int = Field(ge=1, le=1)
    operation: str = Field(pattern=r"^editable_scene$")
    blender_version: str = Field(min_length=1, max_length=80)
    objects: int = Field(ge=1, le=100_000)
    meshes: int = Field(ge=1, le=100_000)
    materials: int = Field(ge=0, le=100_000)
    vertices: int = Field(ge=1, le=10_000_000)
    triangles: int = Field(ge=1, le=20_000_000)
    animations: int = Field(ge=0, le=10_000)
    animated_objects: list[str] = Field(max_length=10_000)
    animation_paths: list[Literal["location", "rotation_euler", "rotation_quaternion", "scale"]] = (
        Field(max_length=4)
    )
    animation_keyframes: int = Field(ge=0, le=1_000_000)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    min_bounds_m: list[float] = Field(min_length=3, max_length=3)
    max_bounds_m: list[float] = Field(min_length=3, max_length=3)
    external_refs: list[str] = Field(max_length=0)
    scripts: list[str] = Field(max_length=0)
    drivers: list[str] = Field(max_length=0)
    packed: bool
    sandbox_network_interfaces: list[Literal["lo"]] = Field(max_length=1)
    sandbox_uid: int = Field(ge=65534, le=65534)
    capability_effective: Literal["0000000000000000"]
    capability_permitted: Literal["0000000000000000"]
    capability_ambient: Literal["0000000000000000"]
    no_new_privileges: Literal[True]

    @model_validator(mode="after")
    def animation_evidence_is_consistent(self) -> BlenderHandoffReport:
        evidence = bool(self.animated_objects and self.animation_paths and self.animation_keyframes)
        empty = (
            not self.animated_objects and not self.animation_paths and self.animation_keyframes == 0
        )
        if (self.animations > 0 and not evidence) or (self.animations == 0 and not empty):
            raise ValueError("animation evidence does not match the action count")
        return self


class BlenderHandoffOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    report: BlenderHandoffReport | None = None
    error_code: str | None = None
    message: str = ""


BLENDER_LIMITS = sandbox.SandboxLimits(
    wall_seconds=300,
    cpu_seconds=300,
    memory_bytes=6144 * sandbox.MB,
    max_input_bytes=300 * sandbox.MB,
    max_output_bytes=1024 * 1024,
    max_file_bytes=512 * sandbox.MB,
    isolate_network=True,
    single_threaded=False,
)


def package_editable_scene(
    source_glb: Path,
    output_blend: Path,
    *,
    limits: sandbox.SandboxLimits = BLENDER_LIMITS,
) -> BlenderHandoffOutcome:
    """Import one validated GLB and save a self-contained editable ``.blend`` file."""

    if source_glb.suffix.lower() != ".glb":
        return BlenderHandoffOutcome(
            ok=False,
            error_code="source_format_invalid",
            message="Blender handoff requires a validated GLB source",
        )
    if output_blend.suffix.lower() != ".blend":
        return BlenderHandoffOutcome(
            ok=False,
            error_code="output_format_invalid",
            message="Blender handoff output must use the .blend extension",
        )

    runner_spool = os.environ.get("BLENDER_RUNNER_SPOOL")
    if runner_spool:
        from worker.blender_runner import submit

        return submit(
            source_glb, output_blend, Path(runner_spool), timeout=limits.wall_seconds + 30
        )
    return _package_locally(source_glb, output_blend, limits=limits)


def _package_locally(
    source_glb: Path,
    output_blend: Path,
    *,
    limits: sandbox.SandboxLimits = BLENDER_LIMITS,
) -> BlenderHandoffOutcome:
    """Trusted-runner implementation; production calls it only in the secretless sidecar."""

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blender-handoff-") as tmp_dir:
        workdir = Path(tmp_dir)
        staged_source = workdir / "input.glb"
        shutil.copyfile(source_glb, staged_source)
        result = sandbox.run(
            "worker.blender_handoff_child",
            [str(workdir)],
            input_path=staged_source,
            limits=limits,
            cwd=workdir,
        )
        if not result.ok:
            failure = result.failure.value if result.failure is not None else "crashed"
            return BlenderHandoffOutcome(
                ok=False,
                error_code=f"sandbox_{failure}",
                message=result.message,
            )
        payload = result.output or {}
        staged_output = workdir / "output.blend"
        report_path = workdir / "report.json"
        verify_path = workdir / "verify.json"
        if payload.get("ok") is not True:
            return BlenderHandoffOutcome(
                ok=False,
                error_code=str(payload.get("code", "blender_failed")),
                message=str(payload.get("message", "Blender produced no handoff file")),
            )
        expected_files = {"input.glb", "output.blend", "report.json", "verify.json"}
        actual_files = {entry.name for entry in workdir.iterdir()}
        if actual_files != expected_files:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="unexpected_output",
                message="Blender handoff produced unexpected files",
            )
        try:
            report_bytes = _read_regular(report_path, max_bytes=1024 * 1024)
            verify_bytes = _read_regular(verify_path, max_bytes=1024 * 1024)
            report = BlenderHandoffReport.model_validate(json.loads(report_bytes))
            verified = BlenderHandoffReport.model_validate(json.loads(verify_bytes))
        except (OSError, ValueError) as exc:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="report_invalid",
                message=str(exc),
            )
        if report != verified:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="verification_mismatch",
                message="reopened Blender file does not match the package report",
            )
        expected_script_sha = hashlib.sha256(
            Path(__file__).with_name("blender_handoff_script.py").read_bytes()
        ).hexdigest()
        if report.script_sha256 != expected_script_sha or not report.packed:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="report_mismatch",
                message="Blender report does not match the fixed script and packed-resource policy",
            )
        try:
            signature = _copy_regular(
                staged_output,
                output_blend,
                max_bytes=512 * sandbox.MB,
                prefix_bytes=7,
            )
        except OSError as exc:
            return BlenderHandoffOutcome(ok=False, error_code="output_missing", message=str(exc))
        if signature != b"BLENDER":
            output_blend.unlink(missing_ok=True)
            return BlenderHandoffOutcome(
                ok=False,
                error_code="output_invalid",
                message="Blender output has an invalid file signature",
            )
        return BlenderHandoffOutcome(ok=True, report=report)


def _read_regular(path: Path, *, max_bytes: int, prefix_only: int | None = None) -> bytes:
    """Read a bounded regular file without following a sandbox-created symlink."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("sandbox output is not a regular file")
        if info.st_nlink != 1:
            raise OSError("sandbox output must not be hard-linked")
        if info.st_size <= 0 or info.st_size > max_bytes:
            raise OSError("sandbox output size is outside the allowed range")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(prefix_only if prefix_only is not None else max_bytes + 1)
    finally:
        os.close(descriptor)


def _copy_regular(source: Path, destination: Path, *, max_bytes: int, prefix_bytes: int) -> bytes:
    """Copy from the exact validated inode, never reopening a sandbox-controlled path."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("sandbox output is not an independent regular file")
        if info.st_size <= 0 or info.st_size > max_bytes:
            raise OSError("sandbox output size is outside the allowed range")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(descriptor, "rb", closefd=False) as input_handle:
            prefix = input_handle.read(prefix_bytes)
            input_handle.seek(0)
            with destination.open("xb") as output_handle:
                shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
        return prefix
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
