"""Secretless filesystem-spool boundary for the privileged Blender isolation launcher."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from worker import sandbox
from worker.blender_handoff import (
    BLENDER_LIMITS,
    BlenderHandoffOutcome,
    _copy_regular,
    _package_locally,
    _read_regular,
)
from worker.quad_remesh import QUAD_REMESH_LIMITS, QuadRemeshOutcome, _remesh_locally

REQUEST_NAME = re.compile(r"^[0-9a-f]{32}$")
POLL_SECONDS = 0.1
MIN_TARGET_FACES = 100
MAX_TARGET_FACES = 100_000
TARGET_FACES_NAME = "target_faces"


def _directories(spool: Path) -> tuple[Path, Path, Path]:
    return spool / "requests", spool / "processing", spool / "responses"


def submit(
    source: Path, destination: Path, spool: Path, *, timeout: float
) -> BlenderHandoffOutcome:
    """Submit a fixed handoff request without sending paths, code, credentials, or argv."""

    requests, _processing, responses = _directories(spool)
    if not requests.is_dir() or not responses.is_dir():
        return BlenderHandoffOutcome(
            ok=False,
            error_code="runner_unavailable",
            message="Blender runner spool is unavailable",
        )
    request_id = uuid.uuid4().hex
    temporary = requests / f".{request_id}.tmp"
    request = requests / request_id
    response = responses / request_id
    temporary.mkdir(mode=0o700)
    try:
        shutil.copyfile(source, temporary / "input.glb")
        os.replace(temporary, request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not response.is_dir():
            time.sleep(POLL_SECONDS)
        if not response.is_dir():
            return BlenderHandoffOutcome(
                ok=False,
                error_code="runner_timeout",
                message="Blender runner did not finish before the deadline",
            )
        try:
            payload = _read_regular(response / "outcome.json", max_bytes=1024 * 1024)
            outcome = BlenderHandoffOutcome.model_validate(json.loads(payload))
        except (OSError, ValueError) as exc:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="runner_response_invalid",
                message=str(exc),
            )
        if not outcome.ok:
            return outcome
        try:
            signature = _copy_regular(
                response / "output.blend",
                destination,
                max_bytes=512 * sandbox.MB,
                prefix_bytes=7,
            )
        except OSError as exc:
            return BlenderHandoffOutcome(
                ok=False,
                error_code="runner_output_invalid",
                message=str(exc),
            )
        if signature != b"BLENDER":
            destination.unlink(missing_ok=True)
            return BlenderHandoffOutcome(
                ok=False,
                error_code="runner_output_invalid",
                message="Blender runner returned an invalid file signature",
            )
        return outcome
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)
        if response.is_dir():
            shutil.rmtree(response)


def submit_quad_remesh(
    source: Path,
    destination: Path,
    target_faces: int,
    spool: Path,
    *,
    timeout: float,
) -> QuadRemeshOutcome:
    """Submit a fixed quad-remesh request; `target_faces` is the only caller-controlled value."""

    if not MIN_TARGET_FACES <= target_faces <= MAX_TARGET_FACES:
        return QuadRemeshOutcome(
            ok=False,
            error_code="target_faces_invalid",
            message="target_faces must be between 100 and 100,000",
        )
    requests, _processing, responses = _directories(spool)
    if not requests.is_dir() or not responses.is_dir():
        return QuadRemeshOutcome(
            ok=False,
            error_code="runner_unavailable",
            message="Blender runner spool is unavailable",
        )
    request_id = uuid.uuid4().hex
    temporary = requests / f".{request_id}.tmp"
    request = requests / request_id
    response = responses / request_id
    temporary.mkdir(mode=0o700)
    try:
        shutil.copyfile(source, temporary / "input.glb")
        (temporary / TARGET_FACES_NAME).write_text(str(target_faces), encoding="ascii")
        os.replace(temporary, request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not response.is_dir():
            time.sleep(POLL_SECONDS)
        if not response.is_dir():
            return QuadRemeshOutcome(
                ok=False,
                error_code="runner_timeout",
                message="Blender runner did not finish before the deadline",
            )
        try:
            payload = _read_regular(response / "outcome.json", max_bytes=1024 * 1024)
            outcome = QuadRemeshOutcome.model_validate(json.loads(payload))
        except (OSError, ValueError) as exc:
            return QuadRemeshOutcome(
                ok=False,
                error_code="runner_response_invalid",
                message=str(exc),
            )
        if not outcome.ok:
            return outcome
        try:
            signature = _copy_regular(
                response / "output.fbx",
                destination,
                max_bytes=512 * sandbox.MB,
                prefix_bytes=7,
            )
        except OSError as exc:
            return QuadRemeshOutcome(
                ok=False,
                error_code="runner_output_invalid",
                message=str(exc),
            )
        if signature != b"Kaydara":
            destination.unlink(missing_ok=True)
            return QuadRemeshOutcome(
                ok=False,
                error_code="runner_output_invalid",
                message="Blender runner returned an invalid file signature",
            )
        return outcome
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)
        if response.is_dir():
            shutil.rmtree(response)


def _process_quad_remesh(claimed: Path, temporary_response: Path) -> QuadRemeshOutcome:
    target_faces_text = _read_regular(claimed / TARGET_FACES_NAME, max_bytes=16).decode("ascii")
    if not target_faces_text.isdecimal():
        return QuadRemeshOutcome(
            ok=False,
            error_code="runner_request_invalid",
            message="Blender runner quad-remesh request has an invalid target_faces value",
        )
    target_faces = int(target_faces_text)
    if not MIN_TARGET_FACES <= target_faces <= MAX_TARGET_FACES:
        return QuadRemeshOutcome(
            ok=False,
            error_code="runner_request_invalid",
            message="Blender runner quad-remesh request has an out-of-bounds target_faces",
        )
    with tempfile.TemporaryDirectory(prefix="sova-blender-runner-") as local_name:
        local = Path(local_name)
        _copy_regular(
            claimed / "input.glb",
            local / "input.glb",
            max_bytes=QUAD_REMESH_LIMITS.max_input_bytes,
            prefix_bytes=4,
        )
        outcome = _remesh_locally(
            local / "input.glb",
            local / "output.fbx",
            target_faces,
            limits=QUAD_REMESH_LIMITS,
        )
        if outcome.ok:
            _copy_regular(
                local / "output.fbx",
                temporary_response / "output.fbx",
                max_bytes=512 * sandbox.MB,
                prefix_bytes=7,
            )
        return outcome


def process_one(spool: Path, request: Path) -> None:
    """Atomically claim and process one fixed-format request."""

    requests, processing, responses = _directories(spool)
    if request.parent != requests or REQUEST_NAME.fullmatch(request.name) is None:
        return
    claimed = processing / request.name
    try:
        os.replace(request, claimed)
    except FileNotFoundError:
        return
    temporary_response = responses / f".{request.name}.tmp"
    final_response = responses / request.name
    files = {entry.name for entry in claimed.iterdir()}
    is_quad_remesh = files == {"input.glb", TARGET_FACES_NAME}
    outcome_type = QuadRemeshOutcome if is_quad_remesh else BlenderHandoffOutcome
    outcome: BlenderHandoffOutcome | QuadRemeshOutcome
    try:
        temporary_response.mkdir(mode=0o700)
        if is_quad_remesh:
            outcome = _process_quad_remesh(claimed, temporary_response)
        elif files == {"input.glb"}:
            with tempfile.TemporaryDirectory(prefix="sova-blender-runner-") as local_name:
                local = Path(local_name)
                _copy_regular(
                    claimed / "input.glb",
                    local / "input.glb",
                    max_bytes=BLENDER_LIMITS.max_input_bytes,
                    prefix_bytes=4,
                )
                outcome = _package_locally(
                    local / "input.glb",
                    local / "output.blend",
                    limits=BLENDER_LIMITS,
                )
                if outcome.ok:
                    _copy_regular(
                        local / "output.blend",
                        temporary_response / "output.blend",
                        max_bytes=512 * sandbox.MB,
                        prefix_bytes=7,
                    )
        else:
            outcome = BlenderHandoffOutcome(
                ok=False,
                error_code="runner_request_invalid",
                message="Blender runner request has unexpected files",
            )
        (temporary_response / "outcome.json").write_text(
            outcome.model_dump_json(), encoding="utf-8"
        )
        os.replace(temporary_response, final_response)
    except (OSError, ValueError) as exc:
        temporary_response.mkdir(mode=0o700, exist_ok=True)
        failure = outcome_type(
            ok=False,
            error_code="runner_failed",
            message=str(exc),
        )
        (temporary_response / "outcome.json").write_text(
            failure.model_dump_json(), encoding="utf-8"
        )
        os.replace(temporary_response, final_response)
    finally:
        shutil.rmtree(claimed, ignore_errors=True)


def main() -> None:
    spool = Path(os.environ.get("BLENDER_RUNNER_SPOOL", "/run/sova-blender")).resolve()
    directories = _directories(spool)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True, mode=0o770)
    requests, _processing, _responses = directories
    while True:
        for request in sorted(requests.iterdir()):
            if request.is_dir() and not request.name.startswith("."):
                process_one(spool, request)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
