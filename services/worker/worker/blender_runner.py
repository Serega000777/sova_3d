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

REQUEST_NAME = re.compile(r"^[0-9a-f]{32}$")
POLL_SECONDS = 0.1


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
    try:
        temporary_response.mkdir(mode=0o700)
        if {entry.name for entry in claimed.iterdir()} != {"input.glb"}:
            outcome = BlenderHandoffOutcome(
                ok=False,
                error_code="runner_request_invalid",
                message="Blender runner request has unexpected files",
            )
        else:
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
        (temporary_response / "outcome.json").write_text(
            outcome.model_dump_json(), encoding="utf-8"
        )
        os.replace(temporary_response, final_response)
    except (OSError, ValueError) as exc:
        temporary_response.mkdir(mode=0o700, exist_ok=True)
        failure = BlenderHandoffOutcome(
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
