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


# --- dedicated scanners (F-082) ----------------------------------------------------------

FRAGMENT_KINDS = ("mesh", "pointcloud")
MIN_COMPONENT_FRACTION = 0.05  # a piece smaller than this share of the biggest (across) is noise
VOXEL_CELLS = 160  # point clouds are meshed on a grid this wide along the longest axis


def pose_matrix(pose: dict[str, Any]) -> np.ndarray:
    """A fragment's placement in the scanner's world, millimetres.

    Scanner software gives a 4x4 matrix; a turntable gives an angle about z (and maybe a
    translation); nothing at all means the fragment is already where it belongs.
    """
    matrix = pose.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 4:
        arr = np.asarray(matrix, dtype=float)
        if tuple(arr.shape) == (4, 4):
            return arr
    transform = np.eye(4)
    azimuth = pose.get("azimuth_deg")
    if isinstance(azimuth, (int, float)):
        # the table had turned the object by `azimuth` when this was captured: turn it back,
        # about the table's axis when the device says where that is
        centre = pose.get("turntable_centre_mm")
        point = (
            np.asarray(centre, dtype=float)
            if isinstance(centre, list) and len(centre) == 3
            else np.zeros(3)
        )
        transform = trimesh.transformations.rotation_matrix(
            -math.radians(float(azimuth)), [0, 0, 1], point=point
        )
    translation = pose.get("translation_mm")
    if isinstance(translation, list) and len(translation) == 3:
        transform[:3, 3] += np.asarray(translation, dtype=float)
    return transform


def _load_fragment(frame: Frame) -> trimesh.Trimesh | trimesh.PointCloud | None:
    loaded = trimesh.load(frame.path, file_type=frame.path.suffix.lstrip("."), process=False)
    if isinstance(loaded, trimesh.Scene):
        merged = as_single_mesh(loaded)
        loaded = merged if merged is not None else trimesh.Trimesh()
    if isinstance(loaded, trimesh.Trimesh) and len(loaded.faces) == 0 and len(loaded.vertices):
        loaded = trimesh.PointCloud(loaded.vertices)  # a PLY of points read as an empty mesh
    if isinstance(loaded, (trimesh.Trimesh, trimesh.PointCloud)) and len(loaded.vertices):
        if isinstance(loaded, trimesh.Trimesh):
            loaded.merge_vertices()  # STL stores every triangle apart; closed means merged
        loaded.apply_transform(pose_matrix(frame.pose))
        return loaded
    return None


def drop_noise(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, int]:
    """Keep the connected pieces that are part of the object; a floating speck is noise.

    Small is not enough to be noise — a scanner's shells break into small islands around
    edges — so a piece goes only when it is small *and* lies outside the space the big
    pieces take up (with a margin)."""
    pieces = mesh.split(only_watertight=False)
    if len(pieces) <= 1:
        return mesh, 0
    size = [float(np.linalg.norm(piece.extents)) for piece in pieces]
    biggest = max(size)
    big = [
        p
        for p, across in zip(pieces, size, strict=True)
        if across >= MIN_COMPONENT_FRACTION * biggest
    ]
    lo = np.min([p.bounds[0] for p in big], axis=0)
    hi = np.max([p.bounds[1] for p in big], axis=0)
    margin = 0.1 * (hi - lo) + 5.0
    lo, hi = lo - margin, hi + margin
    kept = [
        piece
        for piece, across in zip(pieces, size, strict=True)
        if across >= MIN_COMPONENT_FRACTION * biggest
        or bool(np.all(piece.bounds[1] >= lo) and np.all(piece.bounds[0] <= hi))
    ]
    merged = trimesh.util.concatenate(kept)
    assert isinstance(merged, trimesh.Trimesh)
    return merged, len(pieces) - len(kept)


def mesh_from_points(points: np.ndarray) -> trimesh.Trimesh:
    """A closed surface around a point cloud: occupancy on a voxel grid, closed and filled,
    then marching cubes. Coarse next to a scanner's own meshing, but metric and printable."""
    from scipy import ndimage
    from scipy.spatial import cKDTree
    from skimage import measure

    lo, hi = points.min(axis=0), points.max(axis=0)
    span = float((hi - lo).max())
    if span <= 0:
        raise ReconstructionError("degenerate_points", "the point cloud has no extent")
    # cells no finer than the points' own spacing (its 95th percentile: the sparse spots
    # decide), so a one-voxel dilation makes a gap-free shell to fill
    sample = points[:: max(1, len(points) // 5000)]
    spacing = (
        float(np.percentile(cKDTree(sample).query(sample, k=2)[0][:, 1], 95))
        if len(sample) > 1
        else 0.0
    )
    cell = max(span / VOXEL_CELLS, spacing)
    shape = np.ceil((hi - lo) / cell).astype(int) + 7
    grid = np.zeros(shape, dtype=bool)
    index = np.floor((points - lo) / cell).astype(int) + 3
    grid[index[:, 0], index[:, 1], index[:, 2]] = True
    full = np.ones((3, 3, 3), dtype=bool)
    thick = ndimage.binary_dilation(grid, structure=full)
    solid = ndimage.binary_erosion(ndimage.binary_fill_holes(thick), structure=full)
    # a signed distance field puts the surface half a cell inside the voxel boundary, where
    # the points actually are, instead of half a cell outside it
    field = ndimage.distance_transform_edt(solid) - ndimage.distance_transform_edt(~solid)
    try:
        vertices, faces, _, _ = measure.marching_cubes(field, level=0.5)
    except (RuntimeError, ValueError) as exc:
        raise ReconstructionError("no_surface", f"no surface could be built: {exc}") from exc
    mesh = trimesh.Trimesh(vertices=vertices * cell + lo - 3 * cell, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


@register("fusion")
class FusionReconstructor:
    """A dedicated 3D scanner's output (F-082): mesh fragments — or point clouds — already
    metric, each with its pose in the scanner's world, fused into one model.

    Scanner software does the tracking and the meshing; this joins what it delivered,
    drops floating specks, closes small holes and reports the scale as the device's: a
    measurement, not a guess.
    """

    name = "fusion"

    @staticmethod
    def _fuse_meshes(meshes: list[trimesh.Trimesh], details: dict[str, Any]) -> trimesh.Trimesh:
        """Closed fragments are joined as solids (a true union); open shells are stitched."""
        if len(meshes) == 1:
            return meshes[0]
        if all(m.is_volume for m in meshes):
            try:
                union = trimesh.boolean.union(meshes, engine="manifold")
                if isinstance(union, trimesh.Trimesh) and not union.is_empty:
                    details["fusion"] = "union"
                    return union
            except Exception:  # manifold refuses odd input; the stitch below still works
                pass
        merged = trimesh.util.concatenate(meshes)
        assert isinstance(merged, trimesh.Trimesh)
        merged.merge_vertices()
        details["fusion"] = "stitch"
        return merged

    def reconstruct(self, scan: ScanInput, out_dir: Path) -> Reconstruction:
        fragments = [f for f in scan.frames if f.kind in FRAGMENT_KINDS]
        if not fragments:
            raise ReconstructionError(
                "no_fragments", "a scanner session needs mesh or point-cloud fragments"
            )
        meshes: list[trimesh.Trimesh] = []
        clouds: list[np.ndarray] = []
        for frame in sorted(fragments, key=lambda f: f.sequence_no):
            geometry = _load_fragment(frame)
            if isinstance(geometry, trimesh.Trimesh):
                meshes.append(geometry)
            elif isinstance(geometry, trimesh.PointCloud):
                clouds.append(np.asarray(geometry.vertices, dtype=float))

        details: dict[str, Any] = {
            "fragments": len(fragments),
            "mesh_fragments": len(meshes),
            "pointcloud_fragments": len(clouds),
        }
        if meshes:
            # floating specks go first, so they never take part in the union
            sizes = [float(np.linalg.norm(m.extents)) for m in meshes]
            biggest = max(sizes)
            big = [
                m
                for m, size in zip(meshes, sizes, strict=True)
                if size >= MIN_COMPONENT_FRACTION * biggest
            ]
            lo = np.min([m.bounds[0] for m in big], axis=0) - 5.0
            hi = np.max([m.bounds[1] for m in big], axis=0) + 5.0
            kept = [
                m
                for m, size in zip(meshes, sizes, strict=True)
                if size >= MIN_COMPONENT_FRACTION * biggest
                or bool(np.all(m.bounds[1] >= lo) and np.all(m.bounds[0] <= hi))
            ]
            merged = self._fuse_meshes(kept, details)
            merged, dropped = drop_noise(merged)
            details["noise_pieces_dropped"] = dropped + (len(meshes) - len(kept))
            if clouds:
                details["note"] = "point-cloud fragments were left out: the mesh fragments stand"
        else:
            points = np.vstack(clouds)
            details["points"] = int(len(points))
            merged = mesh_from_points(points)
            details["note"] = (
                "meshed from points on a voxel grid; the scanner's own meshing is finer"
            )

        from worker.repair import repair_mesh

        report = repair_mesh(merged)
        details["repair"] = report.delta.model_dump(mode="json")
        details["watertight"] = bool(merged.is_watertight)
        if merged.is_empty or len(merged.faces) == 0:
            raise ReconstructionError("empty_fusion", "the fragments contain no surface")
        merged.apply_translation(-merged.bounds[0])  # sit on z = 0 like every other model

        extent = float(merged.extents.max())
        warning = None
        if scan.scale_hint_mm and abs(scan.scale_hint_mm - extent) > 0.1 * extent:
            warning = (
                f"The scanner measured {extent:.1f} mm across; you said {scan.scale_hint_mm:g} mm. "
                "The scanner's measurement was kept."
            )
        scale = ScaleReport(extent, "device", 0.98, warning)
        turntable = any("azimuth_deg" in f.pose for f in fragments)
        coverage = angular_coverage(scan) if turntable else 1.0

        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "reconstruction.stl"
        merged.export(mesh_path)
        details["faces"] = int(len(merged.faces))
        return Reconstruction(
            mesh_path=mesh_path, provider=self.name, scale=scale, coverage=coverage, details=details
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
