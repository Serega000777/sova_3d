"""T-017: sandbox enforces wall-clock, CPU/memory, input-size and output-size limits."""

import os
from pathlib import Path

import pytest

from worker import sandbox
from worker.sandbox import FailureKind, SandboxLimits

FIXTURE_MODULE = "tests.sandbox_fixture"
POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="rlimits are POSIX only")


FAST = SandboxLimits(wall_seconds=20, isolate_network=False)


def run_fixture(
    mode: str, *, limits: SandboxLimits = FAST, input_path: Path | None = None
) -> sandbox.SandboxResult:
    return sandbox.run(
        FIXTURE_MODULE,
        [mode],
        limits=limits,
        input_path=input_path,
        cwd=Path(__file__).parents[1],
    )


def test_ok_returns_parsed_json() -> None:
    result = run_fixture("ok")
    assert result.ok, result
    assert result.output == {"answer": 42, "env_scrubbed": True}


def test_child_does_not_inherit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_SECRET_KEY", "hunter2")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hunter2")
    result = run_fixture("ok")
    assert result.ok and result.output is not None
    assert result.output["env_scrubbed"] is True


def test_wall_clock_timeout_kills_child() -> None:
    result = run_fixture("sleep", limits=SandboxLimits(wall_seconds=1, isolate_network=False))
    assert not result.ok
    assert result.failure is FailureKind.timeout


def test_crash_is_structured_failure() -> None:
    result = run_fixture("crash")
    assert not result.ok
    assert result.failure is FailureKind.crashed
    assert result.returncode == 3
    assert "boom" in result.stderr_tail


def test_non_json_output_is_rejected() -> None:
    result = run_fixture("garbage")
    assert not result.ok and result.failure is FailureKind.bad_output


def test_output_size_cap() -> None:
    result = run_fixture(
        "flood",
        limits=SandboxLimits(wall_seconds=20, max_output_bytes=1024, isolate_network=False),
    )
    assert not result.ok and result.failure is FailureKind.bad_output


def test_input_size_is_checked_before_launch(tmp_path: Path) -> None:
    big = tmp_path / "big.stl"
    big.write_bytes(b"x" * 2048)
    result = run_fixture(
        "ok",
        input_path=big,
        limits=SandboxLimits(max_input_bytes=1024, isolate_network=False),
    )
    assert not result.ok and result.failure is FailureKind.input_too_large


@POSIX_ONLY
def test_memory_limit_is_enforced() -> None:
    result = run_fixture(
        "allocate",
        limits=SandboxLimits(wall_seconds=30, memory_bytes=256 * sandbox.MB, isolate_network=False),
    )
    assert not result.ok
    assert result.failure is FailureKind.resource_limit, result


@POSIX_ONLY
def test_cpu_limit_is_enforced() -> None:
    result = run_fixture(
        "spin",
        limits=SandboxLimits(wall_seconds=60, cpu_seconds=1, isolate_network=False),
    )
    assert not result.ok
    assert result.failure is FailureKind.resource_limit, result


@POSIX_ONLY
def test_network_isolation_when_available() -> None:
    if not sandbox._unshare_available():
        pytest.skip("unprivileged network namespaces unavailable here")
    result = run_fixture("network", limits=SandboxLimits(wall_seconds=20, isolate_network=True))
    assert result.ok and result.output is not None
    assert result.output["connected"] is False
