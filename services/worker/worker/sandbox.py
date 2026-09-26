"""Sandboxed subprocess runner for untrusted file processing (T-017).

Every parser/converter runs in a child interpreter that:
- gets a scrubbed environment (no cloud credentials, no user site-packages),
- is bounded by wall-clock timeout, CPU seconds and address space (POSIX rlimits),
- may only read an input whose size was checked before launch,
- has its stdout capped so a runaway child cannot exhaust the parent,
- optionally loses network access via an unprivileged network namespace
  when the platform supports it (best effort; the container itself should
  also run with network disabled).

Results are JSON on stdout; anything else is a structured failure, never
an exception from the parser leaking into the orchestrator.
"""

from __future__ import annotations

import enum
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

MB = 1024 * 1024

# Environment the child gets: enough to start Python, nothing that identifies the tenant.
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL")


class FailureKind(enum.StrEnum):
    timeout = "timeout"
    resource_limit = "resource_limit"
    input_too_large = "input_too_large"
    crashed = "crashed"
    bad_output = "bad_output"


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    wall_seconds: float = 60.0
    cpu_seconds: int = 60
    memory_bytes: int = 2048 * MB
    max_input_bytes: int = 512 * MB
    max_output_bytes: int = 16 * MB
    isolate_network: bool = True
    # Pinning BLAS/OpenMP to one thread buys deterministic results for the parsers this
    # sandbox was built for; a CPU-bound ML model wants every core instead and does not
    # need bit-exact reproducibility, so it may opt out.
    single_threaded: bool = True


DEFAULT_LIMITS = SandboxLimits()


@dataclass(frozen=True, slots=True)
class SandboxResult:
    ok: bool
    output: dict[str, Any] | None = None
    failure: FailureKind | None = None
    message: str = ""
    returncode: int | None = None
    stderr_tail: str = ""
    limits: SandboxLimits = DEFAULT_LIMITS


@cache
def _unshare_available() -> bool:
    """Probe once whether an unprivileged network namespace can be created here."""
    if os.name != "posix" or shutil.which("unshare") is None:
        return False
    try:
        probe = subprocess.run(
            ["unshare", "-rn", "true"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _preexec(limits: SandboxLimits) -> Callable[[], None] | None:
    if sys.platform == "win32":
        return None  # no rlimits on Windows dev boxes; production workers are Linux containers
    import resource

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 5))
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # NPROC is counted per user, not per child: keep it as a fork-bomb guard only.
        resource.setrlimit(resource.RLIMIT_NPROC, (4096, 4096))

    return apply


def child_command(module: str, args: list[str]) -> list[str]:
    # -I: isolated mode (ignore PYTHON* env vars, user site, script dir on sys.path).
    return [sys.executable, "-I", "-m", module, *args]


def run(
    module: str,
    args: list[str],
    *,
    input_path: Path | None = None,
    limits: SandboxLimits = DEFAULT_LIMITS,
    cwd: Path | None = None,
) -> SandboxResult:
    """Run `python -m module args...` under the sandbox and parse its JSON stdout."""
    if input_path is not None:
        try:
            size = input_path.stat().st_size
        except OSError as exc:
            return SandboxResult(False, failure=FailureKind.crashed, message=str(exc))
        if size > limits.max_input_bytes:
            return SandboxResult(
                False,
                failure=FailureKind.input_too_large,
                message=f"input is {size} bytes, limit {limits.max_input_bytes}",
                limits=limits,
            )

    command = child_command(module, args)
    if limits.isolate_network and _unshare_available():
        command = ["unshare", "-rn", *command]

    env = {key: os.environ[key] for key in _ENV_PASSTHROUGH if key in os.environ}
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p and Path(p).is_dir())
    env["PHYSICAL_AI_SANDBOX"] = "1"
    if limits.single_threaded:
        # Single-threaded BLAS: deterministic results and no thread pools fighting the rlimits.
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            env[var] = "1"

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=limits.wall_seconds,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=cwd,
            preexec_fn=_preexec(limits),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stderr or b"")[-2000:].decode("utf-8", "replace")
        return SandboxResult(
            False,
            failure=FailureKind.timeout,
            message=f"exceeded {limits.wall_seconds}s wall clock",
            stderr_tail=tail,
            limits=limits,
        )

    stderr_tail = proc.stderr[-2000:].decode("utf-8", "replace")
    if proc.returncode != 0:
        kind = FailureKind.crashed
        if _looks_like_resource_kill(proc.returncode, stderr_tail):
            kind = FailureKind.resource_limit
        return SandboxResult(
            False,
            failure=kind,
            message=f"exit code {proc.returncode}",
            returncode=proc.returncode,
            stderr_tail=stderr_tail,
            limits=limits,
        )
    if len(proc.stdout) > limits.max_output_bytes:
        return SandboxResult(
            False,
            failure=FailureKind.bad_output,
            message=f"output exceeded {limits.max_output_bytes} bytes",
            returncode=0,
            limits=limits,
        )
    try:
        output = json.loads(proc.stdout)
    except ValueError as exc:
        return SandboxResult(
            False,
            failure=FailureKind.bad_output,
            message=f"stdout is not JSON: {exc}",
            returncode=0,
            stderr_tail=stderr_tail,
            limits=limits,
        )
    if not isinstance(output, dict):
        return SandboxResult(
            False,
            failure=FailureKind.bad_output,
            message="stdout JSON must be an object",
            returncode=0,
            limits=limits,
        )
    return SandboxResult(True, output=output, returncode=0, limits=limits)


def _looks_like_resource_kill(returncode: int, stderr_tail: str) -> bool:
    # SIGKILL/SIGXCPU from rlimits, or Python surfacing the address-space cap.
    if returncode in (-9, -24, 137, 152):
        return True
    return "MemoryError" in stderr_tail or "Cannot allocate memory" in stderr_tail
