"""Reconstruction adapters (T-080/T-081, F-002): frames in, mesh out.

The platform must not be married to one photogrammetry provider (constitution: no
provider lock-in), so reconstruction is an interface with swappable implementations and
one rule: whatever comes back is an untrusted mesh, parsed and checked like any upload.

`stub` is the local fixture pipeline — deterministic, offline, no GPU — so the whole scan
path (upload -> finalize -> job -> mesh -> repair -> version) is testable end to end and
a new adapter has something to be compared against.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import trimesh

from worker.importers.common import as_single_mesh

PROVIDERS: dict[str, type[Reconstructor]] = {}


@dataclass(frozen=True, slots=True)
class Frame:
    """One captured frame as the worker sees it."""

    sequence_no: int
    path: Path
    kind: str = "rgb"
    pose: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScanInput:
    frames: tuple[Frame, ...]
    mode: str = "rgb"
    # What the client believes the object's largest dimension is, if anything.
    scale_hint_mm: float | None = None
    scale_confidence: float | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScaleReport:
    """T-082: metric scale is a claim, and the user is told how much to trust it."""

    applied_mm: float
    source: str  # depth | scale_hint | assumed
    confidence: float
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied_mm": round(self.applied_mm, 3),
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "warning": self.warning,
        }


@dataclass(frozen=True, slots=True)
class Reconstruction:
    mesh_path: Path
    provider: str
    scale: ScaleReport
    coverage: float  # 0..1, how much of the object the frames actually saw
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "scale": self.scale.to_dict(),
            "coverage": round(self.coverage, 3),
            **self.details,
        }


class ReconstructionError(RuntimeError):
    """Reconstruction failed for a reason the user can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Reconstructor(Protocol):
    name: str

    def reconstruct(self, scan: ScanInput, out_dir: Path) -> Reconstruction: ...


def register(name: str) -> Callable[[type[Reconstructor]], type[Reconstructor]]:
    def decorator(cls: type[Reconstructor]) -> type[Reconstructor]:
        cls.name = name
        PROVIDERS[name] = cls
        return cls

    return decorator


def reconstructor_for(provider: str) -> Reconstructor:
    try:
        return PROVIDERS[provider]()
    except KeyError:
        raise ReconstructionError(
            "unknown_provider", f"no reconstruction provider named {provider!r}"
        ) from None


def angular_coverage(scan: ScanInput) -> float:
    """How much of a turn around the object the poses cover, 0..1.

    With real poses this is the azimuth spread; without them (plain Expo Go capture) it
    falls back to frame count, which is the honest answer: we do not know where the
    camera was, only how many pictures arrived.
    """
    azimuths = [
        float(frame.pose["azimuth_deg"])
        for frame in scan.frames
        if isinstance(frame.pose.get("azimuth_deg"), (int, float))
    ]
    if len(azimuths) >= 3:
        buckets = {int(a % 360) // 30 for a in azimuths}  # twelve 30° sectors
        return len(buckets) / 12
    return min(len(scan.frames) / 48, 1.0)


@register("stub")
class StubReconstructor:
    """Deterministic local pipeline (T-081).

    It does not do photogrammetry: it builds a convex, printable stand-in whose size
    honours the scale hint and whose silhouette varies with the capture, so every stage
    after reconstruction — cleanup, scale validation, preview, versioning — runs on a
    real mesh. The report says plainly that this is a placeholder.
    """

    name = "stub"

    def reconstruct(self, scan: ScanInput, out_dir: Path) -> Reconstruction:
        if not scan.frames:
            raise ReconstructionError("no_frames", "the scan has no frames to reconstruct")

        # Deterministic per scan: the same frames always give the same mesh.
        digest = hashlib.sha256()
        for frame in sorted(scan.frames, key=lambda f: (f.sequence_no, f.kind)):
            digest.update(str(frame.sequence_no).encode())
            digest.update(frame.path.name.encode())
        seed = int.from_bytes(digest.digest()[:8], "big")
        rng = np.random.default_rng(seed)

        coverage = angular_coverage(scan)
        # A sphere sampled unevenly: more coverage -> rounder, less -> flatter on one side.
        points = rng.normal(size=(512, 3))
        points /= np.linalg.norm(points, axis=1, keepdims=True)
        squash = 0.45 + 0.55 * coverage
        points[:, 2] *= squash
        points[points[:, 1] < 0, 1] *= 0.6 + 0.4 * coverage

        mesh = trimesh.convex.convex_hull(points)
        mesh.apply_translation(-mesh.bounds[0])  # sit on z = 0 like every other model

        scale = self._scale(scan, float(mesh.extents.max()))
        mesh.apply_scale(scale.applied_mm / float(mesh.extents.max()))

        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "reconstruction.stl"
        mesh.export(mesh_path)
        return Reconstruction(
            mesh_path=mesh_path,
            provider=self.name,
            scale=scale,
            coverage=coverage,
            details={
                "frames": len(scan.frames),
                "mode": scan.mode,
                "placeholder": True,
                "note": (
                    "Local stub reconstruction: the shape is a stand-in, the pipeline is real. "
                    "Swap in a photogrammetry provider to get the actual object."
                ),
            },
        )

    def _scale(self, scan: ScanInput, raw_extent: float) -> ScaleReport:
        """T-082: depth beats a user's hint, a hint beats a guess, and we say which it was."""
        if scan.mode == "rgb_depth" and any(f.kind == "depth" for f in scan.frames):
            confidence = 0.9 if scan.scale_hint_mm is None else 0.95
            applied = scan.scale_hint_mm or 120.0
            return ScaleReport(applied, "depth", confidence)
        if scan.scale_hint_mm:
            confidence = float(scan.scale_confidence or 0.6)
            warning = None if confidence >= 0.5 else "The size you gave is a rough estimate."
            return ScaleReport(float(scan.scale_hint_mm), "scale_hint", confidence, warning)
        return ScaleReport(
            100.0,
            "assumed",
            0.1,
            "No depth sensor and no size given: the model is 100 mm across by assumption. "
            "Measure the object and set the size before printing.",
        )


def frame_quality(frames: list[Frame]) -> dict[str, Any]:
    """Aggregate the client's per-frame measurements (T-075) for the report."""
    sharpness = [
        float(f.quality["sharpness"])
        for f in frames
        if isinstance(f.quality.get("sharpness"), (int, float))
    ]
    blurry = [s for s in sharpness if s < 0.35]
    return {
        "frames": len(frames),
        "measured": len(sharpness),
        "mean_sharpness": round(sum(sharpness) / len(sharpness), 3) if sharpness else None,
        "blurry_frames": len(blurry),
    }


def is_degenerate(mesh_path: Path) -> bool:
    """A reconstruction with no volume is a failure, not a model."""
    mesh = as_single_mesh(trimesh.load(mesh_path, force="mesh"))
    if mesh is None or mesh.is_empty:
        return True
    volume = float(mesh.volume)
    return not math.isfinite(volume) or volume <= 0
