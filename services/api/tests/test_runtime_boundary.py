"""Regression coverage for the orchestration-only API container boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_importing_api_routes_does_not_require_worker_package() -> None:
    """The lightweight API image must start without the compute-only worker package."""
    api_root = Path(__file__).resolve().parents[1]
    script = """
import importlib.abc
import sys


class BlockWorker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "worker" or fullname.startswith("worker."):
            raise ModuleNotFoundError("worker is intentionally unavailable in the API runtime")
        return None


sys.meta_path.insert(0, BlockWorker())
from app.main import create_app

assert create_app.__name__ == "create_app"
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
