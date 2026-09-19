"""Intel RealSense depth cameras (D4xx) as a live scanner, through the vendor SDK.

`pyrealsense2` is optional: the driver imports it when opened and says plainly when it is
not installed. A depth camera has no tracking of its own, so this driver works with a
turntable: it takes one point-cloud fragment per step and labels each with the table's
angle; the platform's fusion turns them back into place. Depth is clipped to `range_mm`
so the table and the room do not end up in the model.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import numpy as np

from physical_ai_scanner.drivers import register
from physical_ai_scanner.drivers.base import DeviceInfo, Fragment


@register("realsense")
class RealSenseScanner:
    def __init__(
        self,
        steps: int = 12,
        range_mm: float = 600.0,
        min_range_mm: float = 150.0,
        width: int = 640,
        height: int = 480,
        prompt: bool = True,
    ) -> None:
        self.steps = max(1, int(steps))
        self.range_mm = float(range_mm)
        self.min_range_mm = float(min_range_mm)
        self.width, self.height = int(width), int(height)
        self.prompt = prompt
        self._pipeline: Any = None
        self._rs: Any = None
        self._serial: str | None = None

    def open(self) -> DeviceInfo:
        try:
            import pyrealsense2 as rs
        except ImportError as exc:
            raise RuntimeError(
                "the RealSense driver needs the vendor SDK: pip install pyrealsense2 "
                "(or `uv sync --extra realsense`)"
            ) from exc
        self._rs = rs
        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, 30)
        profile = pipeline.start(config)
        device = profile.get_device()
        self._serial = str(device.get_info(rs.camera_info.serial_number))
        self._pipeline = pipeline
        return DeviceInfo(
            vendor="Intel",
            model=str(device.get_info(rs.camera_info.name)),
            driver="realsense",
            serial=self._serial,
            accuracy_mm=2.0,
            turntable=True,
        )

    def _cloud(self) -> np.ndarray:
        rs = self._rs
        assert self._pipeline is not None
        for _ in range(15):  # let auto-exposure settle
            frames = self._pipeline.wait_for_frames()
        depth = frames.get_depth_frame()
        points = rs.pointcloud().calculate(depth)
        vertices = np.asanyarray(points.get_vertices()).view(np.float32).reshape(-1, 3) * 1000.0
        distance = np.linalg.norm(vertices, axis=1)
        keep = (distance > self.min_range_mm) & (distance < self.range_mm)
        cloud: np.ndarray = np.asarray(vertices[keep], dtype=float)
        return cloud

    def fragments(self) -> Iterator[Fragment]:
        import trimesh

        for step in range(self.steps):
            azimuth = 360.0 * step / self.steps
            if self.prompt and step > 0:
                input(f"turn the table to {azimuth:.0f}° and press Enter… ")
            cloud = self._cloud()
            if len(cloud) < 100:
                continue
            data = io.BytesIO()
            trimesh.PointCloud(cloud).export(data, file_type="ply")
            yield Fragment(
                sequence_no=step,
                kind="pointcloud",
                filename=f"depth_{step:03d}.ply",
                data=data.getvalue(),
                pose={"azimuth_deg": azimuth},
                quality={"points": int(len(cloud)), "angle_deg": azimuth},
            )

    def close(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
