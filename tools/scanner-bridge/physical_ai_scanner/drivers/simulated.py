"""A simulated turntable scanner: a known object, delivered in angular slices.

For demos, tests and the first run without hardware. The object is a bracket with two
holes — 120 × 60 × 25 mm — so the fused result can be checked against known numbers.
"""

from __future__ import annotations

import io
import math
import time
from collections.abc import Iterator

import numpy as np
import trimesh

from physical_ai_scanner.drivers import register
from physical_ai_scanner.drivers.base import DeviceInfo, Fragment


def bracket() -> trimesh.Trimesh:
    """A plate with a ring standing on it — 120 × 60 × 40 mm, an obviously scanned shape."""
    plate = trimesh.creation.box(extents=(120, 60, 25))
    plate.apply_translation((60, 30, 12.5))
    ring = trimesh.creation.annulus(r_min=10.0, r_max=16.0, height=15.0, sections=48)
    ring.apply_translation((90, 30, 25 + 7.5))
    merged = trimesh.util.concatenate([plate, ring])
    assert isinstance(merged, trimesh.Trimesh)
    return merged


@register("simulated")
class SimulatedScanner:
    """Turns once around the object in `steps`, handing over the faces it can see from each
    angle (as open shells, the way a real scanner does), plus a couple of specks of noise."""

    def __init__(self, steps: int = 8, delay_s: float = 0.0, noise: bool = True) -> None:
        self.steps = max(3, int(steps))
        self.delay_s = float(delay_s)
        self.noise = noise
        self._object = bracket()  # the same object every run: results are checkable

    def open(self) -> DeviceInfo:
        return DeviceInfo(
            vendor="Physical AI",
            model="Simulated turntable",
            driver="simulated",
            accuracy_mm=0.05,
            turntable=True,
        )

    def fragments(self) -> Iterator[Fragment]:
        mesh = self._object
        centre = mesh.bounds.mean(axis=0)
        normals = np.asarray(mesh.face_normals, dtype=float)
        for step in range(self.steps):
            azimuth = 360.0 * step / self.steps
            # the scanner looks from this angle, slightly above: it sees faces turned to it
            view = np.array([math.cos(math.radians(azimuth)), math.sin(math.radians(azimuth)), 0.4])
            view /= np.linalg.norm(view)
            facing = (normals @ view) > 0.15
            # and the top is always visible from above
            facing |= normals[:, 2] > 0.9
            piece = mesh.copy()
            piece.update_faces(facing)
            piece.remove_unreferenced_vertices()
            # the device reports fragments in its own world: the table has turned the object
            # by `azimuth`, so the fragment arrives rotated and the pose says by how much
            turn = trimesh.transformations.rotation_matrix(
                math.radians(azimuth), [0, 0, 1], point=centre
            )
            piece.apply_transform(turn)
            data = io.BytesIO()
            piece.export(data, file_type="ply")
            yield Fragment(
                sequence_no=step,
                kind="mesh",
                filename=f"fragment_{step:03d}.ply",
                data=data.getvalue(),
                pose={"azimuth_deg": azimuth, "turntable_centre_mm": centre.tolist()},
                quality={"faces": int(len(piece.faces)), "angle_deg": azimuth},
            )
            if self.delay_s:
                time.sleep(self.delay_s)
        if self.noise:
            speck = trimesh.creation.icosphere(subdivisions=1, radius=0.4)
            speck.apply_translation((300, 300, 40))
            data = io.BytesIO()
            speck.export(data, file_type="ply")
            yield Fragment(
                sequence_no=self.steps,
                kind="mesh",
                filename="noise.ply",
                data=data.getvalue(),
                quality={"faces": int(len(speck.faces)), "note": "simulated dust"},
            )

    def close(self) -> None:
        return None
