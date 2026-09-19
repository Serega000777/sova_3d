"""Any scanner whose software saves files: watch the folder it saves into.

Revo Scan, Creality Scan, EXScan, Artec Studio — every vendor's software can save fragments
or the fused mesh as PLY/STL/OBJ, most of them automatically. Point this driver at that
folder and each new file becomes a fragment the moment it is fully written. A sidecar
`<name>.json` beside a file, when the software (or you) writes one, carries its pose:
`{"matrix": [[...4x4...]]}` or `{"azimuth_deg": 45}`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from physical_ai_scanner.drivers import register
from physical_ai_scanner.drivers.base import DeviceInfo, Fragment

FRAGMENT_SUFFIXES = (".ply", ".stl", ".obj")


def _settled(path: Path, wait_s: float) -> bool:
    """A file is ready when its size stops changing: vendors write big meshes in chunks."""
    try:
        before = path.stat().st_size
    except OSError:
        return False
    time.sleep(wait_s)
    try:
        return path.stat().st_size == before and before > 0
    except OSError:
        return False


def _pose_beside(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.exists():
        sidecar = path.with_suffix(".json")
    if not sidecar.exists():
        return {}
    try:
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


@register("folder")
class FolderScanner:
    """Fragments are the files that appear in `path`; the scan ends after `idle_s` seconds
    without a new one (or on Ctrl-C). Files already there when the scan starts count
    unless `fresh_only` is set."""

    def __init__(
        self,
        path: str,
        idle_s: float = 20.0,
        settle_s: float = 0.5,
        poll_s: float = 0.5,
        fresh_only: bool = False,
        vendor: str = "Folder",
        model: str = "vendor software export",
    ) -> None:
        self.path = Path(path)
        self.idle_s = float(idle_s)
        self.settle_s = float(settle_s)
        self.poll_s = float(poll_s)
        self.fresh_only = fresh_only
        self.vendor = vendor
        self.model = model
        self._seen: set[Path] = set()

    def open(self) -> DeviceInfo:
        if not self.path.is_dir():
            raise FileNotFoundError(f"{self.path} is not a folder")
        if self.fresh_only:
            self._seen = set(self._candidates())
        return DeviceInfo(vendor=self.vendor, model=self.model, driver="folder")

    def _candidates(self) -> list[Path]:
        return sorted(
            p for p in self.path.iterdir() if p.is_file() and p.suffix.lower() in FRAGMENT_SUFFIXES
        )

    def fragments(self) -> Iterator[Fragment]:
        sequence = 0
        last_new = time.monotonic()
        while True:
            fresh = [p for p in self._candidates() if p not in self._seen]
            for path in fresh:
                if not _settled(path, self.settle_s):
                    continue  # still being written; next round
                self._seen.add(path)
                last_new = time.monotonic()
                data = path.read_bytes()
                yield Fragment(
                    sequence_no=sequence,
                    kind="mesh",
                    filename=path.name,
                    data=data,
                    pose=_pose_beside(path),
                    quality={"bytes": len(data), "file": path.name},
                )
                sequence += 1
            if time.monotonic() - last_new > self.idle_s:
                return
            time.sleep(self.poll_s)

    def close(self) -> None:
        return None
