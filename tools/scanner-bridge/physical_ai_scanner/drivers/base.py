"""What every driver delivers: who the device is, and fragments as they come."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FragmentKind = Literal["mesh", "pointcloud"]


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Goes into the scan session's capabilities: the platform records what scanned."""

    vendor: str
    model: str
    driver: str
    serial: str | None = None
    accuracy_mm: float | None = None
    color: bool = False
    turntable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "scanner",
            "vendor": self.vendor,
            "model": self.model,
            "driver": self.driver,
            "serial": self.serial,
            "accuracy_mm": self.accuracy_mm,
            "color": self.color,
            "turntable": self.turntable,
        }


@dataclass(frozen=True, slots=True)
class Fragment:
    """One piece of the object, metric millimetres, in the scanner's world frame."""

    sequence_no: int
    kind: FragmentKind
    filename: str  # .ply / .stl / .obj — what the platform accepts as a fragment
    data: bytes
    pose: dict[str, Any] = field(default_factory=dict)  # {"matrix": 4x4} or {"azimuth_deg": a}
    quality: dict[str, Any] = field(default_factory=dict)  # points, faces, sharpness…

    @property
    def content_type(self) -> str:
        return {
            "ply": "model/ply",
            "stl": "model/stl",
            "obj": "model/obj",
        }[self.filename.rsplit(".", 1)[-1].lower()]


class Driver(Protocol):
    def open(self) -> DeviceInfo: ...

    def fragments(self) -> Iterator[Fragment]:
        """Yields until the scan is over: the device stops, the folder is done, or Ctrl-C."""
        ...

    def close(self) -> None: ...
