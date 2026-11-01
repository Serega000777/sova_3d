"""Quad-dominant retopology for a validated Sova GLB, exported as FBX (P1 Smart low-poly
preset / quad topology), with bounded active-UV surface projection when the source has UVs.

glTF/GLB cannot carry quad faces — the format triangulates on export — so this fixed
operation targets FBX, which Blender's own exporter writes as real polygons. The untrusted
mesh runs Blender's built-in QuadriFlow remesher inside the same isolation boundary as the
Blender handoff (`blender_handoff.py`): a descendant of the scrubbed worker sandbox with
auto-execution disabled, or the secretless `blender-runner` sidecar when configured. The
only caller-controlled value is `target_faces`, a bounded integer re-validated at every
layer; no Python, add-ons, filenames, paths or Blender switches are ever accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from worker import sandbox
from worker.blender_handoff import _copy_regular, _read_regular


class QuadRemeshMaterialReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=200)
    diffuse_rgba: list[float] = Field(min_length=4, max_length=4)
    texture_sha256s: list[str] = Field(max_length=32)
    source_faces: int = Field(ge=0, le=300_000)
    output_faces: int = Field(ge=0, le=200_000)

    @model_validator(mode="after")
    def validate_material_evidence(self) -> QuadRemeshMaterialReport:
        if any(value < 0 or value > 1 for value in self.diffuse_rgba):
            raise ValueError("quad-remesh diffuse colour is outside 0..1")
        if any(
            len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
            for value in self.texture_sha256s
        ):
            raise ValueError("quad-remesh texture digest is invalid")
        if self.texture_sha256s != sorted(set(self.texture_sha256s)):
            raise ValueError("quad-remesh texture digests are not canonical")
        return self


class QuadRemeshObjectReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=200)
    faces: int = Field(ge=1, le=200_000)
    quad_faces: int = Field(ge=0, le=200_000)
    triangle_faces: int = Field(ge=0, le=200_000)
    other_faces: int = Field(ge=0, le=200_000)
    vertices: int = Field(ge=1, le=1_000_000)
    quad_ratio: float = Field(ge=0, le=1)
    source_uv_layers: int = Field(ge=0, le=16)
    uv_layers: int = Field(ge=0, le=1)
    uv_coordinates: int = Field(ge=0, le=4_000_000)
    uv_bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)
    uv_transfer: Literal["none", "active_surface_projected"]
    materials: list[QuadRemeshMaterialReport] = Field(max_length=64)
    material_transfer: Literal["none", "single_slot_preserved", "nearest_source_polygon"]

    @model_validator(mode="after")
    def validate_uv_evidence(self) -> QuadRemeshObjectReport:
        if self.source_uv_layers == 0:
            if (
                self.uv_layers != 0
                or self.uv_coordinates != 0
                or self.uv_bounds is not None
                or self.uv_transfer != "none"
            ):
                raise ValueError("quad-remesh UV evidence invents data for the source")
        elif (
            self.uv_layers != 1
            or self.uv_coordinates <= 0
            or self.uv_bounds is None
            or self.uv_transfer != "active_surface_projected"
            or self.uv_bounds[0] > self.uv_bounds[2]
            or self.uv_bounds[1] > self.uv_bounds[3]
        ):
            raise ValueError("quad-remesh UV transfer evidence is inconsistent")
        expected_material_transfer = (
            "none"
            if not self.materials
            else "single_slot_preserved"
            if len(self.materials) == 1
            else "nearest_source_polygon"
        )
        if self.material_transfer != expected_material_transfer:
            raise ValueError("quad-remesh material transfer evidence is inconsistent")
        if (
            any(material.texture_sha256s for material in self.materials)
            and self.source_uv_layers == 0
        ):
            raise ValueError("quad-remesh texture evidence requires source UVs")
        if (
            self.materials
            and sum(material.output_faces for material in self.materials) != self.faces
        ):
            raise ValueError("quad-remesh output material assignments do not cover every face")
        return self


class QuadRemeshReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: int = Field(ge=4, le=4)
    operation: str = Field(pattern=r"^quad_remesh$")
    blender_version: str = Field(min_length=1, max_length=80)
    target_faces: int = Field(ge=100, le=100_000)
    objects: int = Field(ge=1, le=64)
    faces: int = Field(ge=1, le=12_800_000)
    quad_faces: int = Field(ge=0, le=12_800_000)
    triangle_faces: int = Field(ge=0, le=12_800_000)
    other_faces: int = Field(ge=0, le=12_800_000)
    vertices: int = Field(ge=1, le=64_000_000)
    quad_ratio: float = Field(ge=0, le=1)
    per_object: list[QuadRemeshObjectReport] = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sandbox_network_interfaces: list[Literal["lo"]] = Field(max_length=1)
    sandbox_uid: int = Field(ge=65534, le=65534)
    capability_effective: Literal["0000000000000000"]
    capability_permitted: Literal["0000000000000000"]
    capability_ambient: Literal["0000000000000000"]
    no_new_privileges: Literal[True]

    @model_validator(mode="after")
    def validate_aggregate_matches_objects(self) -> QuadRemeshReport:
        if len(self.per_object) != self.objects:
            raise ValueError("quad-remesh objects count does not match per_object entries")
        if (
            self.faces != sum(entry.faces for entry in self.per_object)
            or self.quad_faces != sum(entry.quad_faces for entry in self.per_object)
            or self.triangle_faces != sum(entry.triangle_faces for entry in self.per_object)
            or self.other_faces != sum(entry.other_faces for entry in self.per_object)
            or self.vertices != sum(entry.vertices for entry in self.per_object)
        ):
            raise ValueError("quad-remesh aggregate totals do not match per_object entries")
        expected_ratio = round(self.quad_faces / self.faces, 4) if self.faces else 0.0
        if abs(self.quad_ratio - expected_ratio) > 1e-9:
            raise ValueError("quad-remesh quad_ratio does not match the aggregate totals")
        names = [entry.name for entry in self.per_object]
        if len(set(names)) != len(names):
            raise ValueError("quad-remesh per_object names are not unique")
        return self


class QuadRemeshOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    report: QuadRemeshReport | None = None
    error_code: str | None = None
    message: str = ""


QUAD_REMESH_LIMITS = sandbox.SandboxLimits(
    wall_seconds=750,
    cpu_seconds=750,
    memory_bytes=6144 * sandbox.MB,
    max_input_bytes=300 * sandbox.MB,
    max_output_bytes=1024 * 1024,
    max_file_bytes=512 * sandbox.MB,
    isolate_network=True,
    single_threaded=False,
)


def remesh_quads(
    source_glb: Path,
    output_fbx: Path,
    target_faces: int,
    *,
    limits: sandbox.SandboxLimits = QUAD_REMESH_LIMITS,
) -> QuadRemeshOutcome:
    """Remesh every mesh object (up to 64) in a validated GLB into quad-dominant topology,
    each independently targeting `target_faces`, saved together as one FBX. World transforms
    are untouched; only each object's own mesh data is rebuilt."""

    if source_glb.suffix.lower() != ".glb":
        return QuadRemeshOutcome(
            ok=False,
            error_code="source_format_invalid",
            message="quad-remesh requires a validated GLB source",
        )
    if output_fbx.suffix.lower() != ".fbx":
        return QuadRemeshOutcome(
            ok=False,
            error_code="output_format_invalid",
            message="quad-remesh output must use the .fbx extension",
        )
    if not 100 <= target_faces <= 100_000:
        return QuadRemeshOutcome(
            ok=False,
            error_code="target_faces_invalid",
            message="target_faces must be between 100 and 100,000",
        )

    runner_spool = os.environ.get("BLENDER_RUNNER_SPOOL")
    if runner_spool:
        from worker.blender_runner import submit_quad_remesh

        return submit_quad_remesh(
            source_glb,
            output_fbx,
            target_faces,
            Path(runner_spool),
            timeout=limits.wall_seconds + 30,
        )
    return _remesh_locally(source_glb, output_fbx, target_faces, limits=limits)


def _remesh_locally(
    source_glb: Path,
    output_fbx: Path,
    target_faces: int,
    *,
    limits: sandbox.SandboxLimits = QUAD_REMESH_LIMITS,
) -> QuadRemeshOutcome:
    """Trusted-runner implementation; production calls it only in the secretless sidecar."""

    output_fbx.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="quad-remesh-") as tmp_dir:
        workdir = Path(tmp_dir)
        staged_source = workdir / "input.glb"
        shutil.copyfile(source_glb, staged_source)
        result = sandbox.run(
            "worker.quad_remesh_child",
            [str(workdir), str(target_faces)],
            input_path=staged_source,
            limits=limits,
            cwd=workdir,
        )
        if not result.ok:
            failure = result.failure.value if result.failure is not None else "crashed"
            return QuadRemeshOutcome(
                ok=False,
                error_code=f"sandbox_{failure}",
                message=result.message,
            )
        payload = result.output or {}
        staged_output = workdir / "output.fbx"
        report_path = workdir / "report.json"
        verify_path = workdir / "verify.json"
        if payload.get("ok") is not True:
            return QuadRemeshOutcome(
                ok=False,
                error_code=str(payload.get("code", "blender_failed")),
                message=str(payload.get("message", "Blender produced no quad-remesh file")),
            )
        expected_files = {"input.glb", "output.fbx", "report.json", "verify.json"}
        actual_files = {entry.name for entry in workdir.iterdir()}
        if actual_files != expected_files:
            return QuadRemeshOutcome(
                ok=False,
                error_code="unexpected_output",
                message="quad-remesh produced unexpected files",
            )
        try:
            report_bytes = _read_regular(report_path, max_bytes=1024 * 1024)
            verify_bytes = _read_regular(verify_path, max_bytes=1024 * 1024)
            report = QuadRemeshReport.model_validate(json.loads(report_bytes))
            verified = QuadRemeshReport.model_validate(json.loads(verify_bytes))
        except (OSError, ValueError) as exc:
            return QuadRemeshOutcome(
                ok=False,
                error_code="report_invalid",
                message=str(exc),
            )
        if report != verified:
            return QuadRemeshOutcome(
                ok=False,
                error_code="verification_mismatch",
                message="reopened quad-remesh FBX does not match the package report",
            )
        expected_script_sha = hashlib.sha256(
            Path(__file__).with_name("quad_remesh_script.py").read_bytes()
        ).hexdigest()
        if report.script_sha256 != expected_script_sha or report.target_faces != target_faces:
            return QuadRemeshOutcome(
                ok=False,
                error_code="report_mismatch",
                message="quad-remesh report does not match the fixed script and request",
            )
        try:
            signature = _copy_regular(
                staged_output,
                output_fbx,
                max_bytes=512 * sandbox.MB,
                prefix_bytes=7,
            )
        except OSError as exc:
            return QuadRemeshOutcome(ok=False, error_code="output_missing", message=str(exc))
        if signature != b"Kaydara":  # Blender's exporter only writes binary FBX
            output_fbx.unlink(missing_ok=True)
            return QuadRemeshOutcome(
                ok=False,
                error_code="output_invalid",
                message="quad-remesh output has an invalid file signature",
            )
        return QuadRemeshOutcome(ok=True, report=report)
