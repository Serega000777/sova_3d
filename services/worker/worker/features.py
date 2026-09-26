"""Feature recognition on a mesh (T-159, F-024) and the profile a parametric rebuild needs
(T-160, F-011).

A scan or an imported mesh has no history: it is triangles. This module reads the history
back out of them — deterministically, no learning involved — the way a machinist would with
a caliper and a square:

* the part is put in its own frame (oriented bounding box; the direction along which its
  cross-section changes least becomes Z, the way it would sit on a mill table);
* it is sliced along Z; every slice is a set of closed loops; a loop is a circle, a
  rectangle (sharp, rounded or chamfered corners) or a polygon;
* runs of slices that look alike are one *band* of the part — an extrusion of that outline
  with those holes — and the height where the outline changes is found by bisection;
* slices that shrink smoothly towards a face are a fillet or a chamfer on its edges;
* circles tracked across slices are holes and bosses (along Z here, along X and Y from the
  other two slicing directions); a ripple in a hole's radius with a standard pitch is a
  thread; equal holes in a line or on a circle are a pattern; a mirrored or rotated copy of
  the surface that lands on itself is a symmetry.

The `Reconstruction` is what the API needs to write an OperationPlan the kernel can run;
`deviation()` then says how far that rebuild is from the scan, in millimetres, so the user
decides with numbers rather than hope. Everything here runs in the sandboxed child like any
other work on an uploaded mesh.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Literal

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from worker.importers.common import as_single_mesh, to_platform_axes

Axis = Literal["x", "y", "z"]
Kind = Literal["circle", "rectangle", "polygon"]

# ISO 261 coarse pitches, mm — what a ripple in a hole's radius is compared against
ISO_COARSE_PITCH_MM: dict[float, float] = {
    1.6: 0.35,
    2.0: 0.4,
    2.5: 0.45,
    3.0: 0.5,
    4.0: 0.7,
    5.0: 0.8,
    6.0: 1.0,
    8.0: 1.25,
    10.0: 1.5,
    12.0: 1.75,
    14.0: 2.0,
    16.0: 2.0,
    20.0: 2.5,
}
MAX_POLYGON_POINTS = 256  # the kernel's profile limit
_AXIS_INDEX: dict[str, int] = {"x": 0, "y": 1, "z": 2}


# --- contracts ---------------------------------------------------------------------------------


class FeatureRequest(BaseModel):
    tolerance_mm: float = Field(default=0.2, gt=0.01, le=5.0)  # what counts as "the same"
    max_levels: int = Field(default=64, ge=8, le=200)  # slices along the extrusion axis
    samples: int = Field(default=3000, ge=200, le=20000)  # surface points for the deviation
    threads: bool = True


class Loop(BaseModel):
    """One closed outline in a slice, in the part's own XY frame (mm)."""

    kind: Kind
    centre_mm: tuple[float, float]
    area_mm2: float
    diameter_mm: float | None = None  # circle
    width_mm: float | None = None  # rectangle, along X
    depth_mm: float | None = None  # rectangle, along Y
    corner_radius_mm: float | None = None  # rounded rectangle
    chamfer_mm: float | None = None  # chamfered rectangle
    points_mm: list[tuple[float, float]] | None = None  # polygon, simplified, ≤ 256


class EdgeFeature(BaseModel):
    kind: Literal["fillet", "chamfer"]
    where: Literal["vertical", "top", "bottom"]
    size_mm: float
    count: int = 1


class Band(BaseModel):
    """A stretch of the part along Z whose slices all look alike: an extrusion."""

    z0_mm: float
    z1_mm: float
    outer: list[Loop]
    holes: list[Loop]  # inner loops that run the whole band
    levels: int  # how many slices agreed


class Cylinder(BaseModel):
    kind: Literal["hole", "boss", "body"]
    axis: Axis
    centre_mm: tuple[float, float, float]  # of the cylinder's lower end, part frame
    diameter_mm: float
    length_mm: float
    through: bool
    from_face: Literal["+", "-", "inside"] = "+"  # which end of the axis it opens on
    confidence: float = Field(ge=0.0, le=1.0)


class Thread(BaseModel):
    on: Literal["hole", "boss"]
    axis: Axis
    centre_mm: tuple[float, float, float]
    major_diameter_mm: float
    minor_diameter_mm: float
    pitch_mm: float
    designation: str | None  # "M6x1.0" when it is a standard size
    confidence: float = Field(ge=0.0, le=1.0)


class Symmetry(BaseModel):
    mirror: list[Axis]  # planes normal to these axes through the part's centre
    rotational_order: int | None = None  # n-fold about Z, None when there is none
    axisymmetric: bool = False


class Pattern(BaseModel):
    kind: Literal["linear", "circular", "grid"]
    count: int
    diameter_mm: float
    pitch_mm: float | None = None  # linear
    pitch_deg: float | None = None  # circular
    centre_mm: tuple[float, float]
    radius_mm: float | None = None  # circular
    columns: int | None = None  # grid
    rows: int | None = None
    pitch_x_mm: float | None = None
    pitch_y_mm: float | None = None


class Plane(BaseModel):
    normal: tuple[float, float, float]
    offset_mm: float
    area_mm2: float


class Reconstruction(BaseModel):
    """What the parametric rebuild is made of, in the part's own frame."""

    frame_transform: list[float]  # 16 values, row-major: scan coordinates → part frame
    extents_mm: tuple[float, float, float]
    bands: list[Band]
    top_edge: EdgeFeature | None = None
    bottom_edge: EdgeFeature | None = None
    side_holes: list[Cylinder] = Field(default_factory=list)  # along X and Y
    fidelity: Literal["prismatic", "stepped", "freeform"]
    levels: int
    unexplained_levels: int


class FeatureReport(BaseModel):
    ok: bool
    message: str | None = None
    faces: int = 0
    watertight: bool = False
    extents_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    planes: list[Plane] = Field(default_factory=list)
    cylinders: list[Cylinder] = Field(default_factory=list)
    edges: list[EdgeFeature] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    symmetry: Symmetry = Field(default_factory=lambda: Symmetry(mirror=[]))
    patterns: list[Pattern] = Field(default_factory=list)
    reconstruction: Reconstruction | None = None
    warnings: list[str] = Field(default_factory=list)


class Deviation(BaseModel):
    ok: bool
    message: str | None = None
    tolerance_mm: float = 0.2
    mean_mm: float = 0.0
    p95_mm: float = 0.0
    max_mm: float = 0.0
    within_tolerance: float = 0.0  # fraction of sample points closer than the tolerance
    samples: int = 0


# --- 2D helpers ---------------------------------------------------------------------------------


def _loops_from_segments(segments: np.ndarray, snap_mm: float = 1e-4) -> list[np.ndarray]:
    """Chain a slice's unordered segments into closed rings of points."""
    if len(segments) == 0:
        return []
    pts = segments.reshape(-1, 2)
    keys = np.round(pts / snap_mm).astype(np.int64)
    index: dict[tuple[int, int], int] = {}
    ids = np.empty(len(pts), dtype=np.int64)
    coords: list[np.ndarray] = []
    for i, key in enumerate(map(tuple, keys)):
        found = index.get(key)
        if found is None:
            found = len(coords)
            index[key] = found
            coords.append(pts[i])
        ids[i] = found
    adjacency: dict[int, list[int]] = {}
    for a, b in ids.reshape(-1, 2):
        if a == b:
            continue
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    seen: set[int] = set()
    loops: list[np.ndarray] = []
    for start in adjacency:
        if start in seen:
            continue
        ring = [start]
        seen.add(start)
        previous, current = -1, start
        while True:
            options = [n for n in adjacency[current] if n != previous and n not in seen]
            if not options:
                break
            previous, current = current, options[0]
            ring.append(current)
            seen.add(current)
        if len(ring) >= 3 and start in adjacency.get(current, []):
            loops.append(np.array([coords[i] for i in ring], dtype=float))
    return loops


def _area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def _centroid(points: np.ndarray) -> np.ndarray:
    x, y = points[:, 0], points[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    signed = cross.sum() / 2.0
    if abs(signed) < 1e-12:
        return points.mean(axis=0)
    cx = ((x + np.roll(x, -1)) * cross).sum() / (6.0 * signed)
    cy = ((y + np.roll(y, -1)) * cross).sum() / (6.0 * signed)
    return np.array([cx, cy])


def _contains(ring: np.ndarray, point: np.ndarray) -> bool:
    """Even-odd point-in-polygon."""
    x, y = point
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1)
            if x < x1 + t * (x2 - x1):
                inside = not inside
    return inside


def _rdp(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas–Peucker on an open polyline."""
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    seg = end - start
    length = float(np.hypot(*seg))
    if length < 1e-12:
        dist = np.hypot(*(points - start).T)
    else:
        rel = points - start
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / length
    idx = int(np.argmax(dist))
    if dist[idx] > tolerance:
        left = _rdp(points[: idx + 1], tolerance)
        right = _rdp(points[idx:], tolerance)
        return np.vstack([left[:-1], right])
    return np.vstack([start, end])


def _simplify_ring(ring: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas–Peucker on a closed ring: split at the two points farthest apart."""
    if len(ring) < 4:
        return ring
    i = 0
    j = int(np.argmax(np.hypot(*(ring - ring[0]).T)))
    if j == 0:
        return ring
    first = _rdp(ring[i : j + 1], tolerance)
    second = _rdp(np.vstack([ring[j:], ring[:1]]), tolerance)
    out = np.vstack([first[:-1], second[:-1]])
    return out if len(out) >= 3 else ring


def _describe_loop(ring: np.ndarray, tolerance: float) -> Loop:
    """A ring becomes a circle, a rectangle (sharp, rounded or chamfered) or a polygon."""
    area = _area(ring)
    centre = _centroid(ring)
    radii = np.hypot(*(ring - centre).T)
    mean_r = float(radii.mean()) if len(radii) else 0.0
    if len(ring) >= 8 and mean_r > 0 and float(radii.std()) / mean_r < 0.02:
        return Loop(
            kind="circle",
            centre_mm=(round(float(centre[0]), 3), round(float(centre[1]), 3)),
            area_mm2=round(area, 3),
            diameter_mm=round(2 * mean_r, 3),
        )

    lo, hi = ring.min(axis=0), ring.max(axis=0)
    width, depth = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    box_area = width * depth
    rect = _rectangle_corners(ring, lo, hi, tolerance)
    if rect is not None and box_area > 0:
        corner_radius, chamfer = rect
        return Loop(
            kind="rectangle",
            centre_mm=(round(float((lo[0] + hi[0]) / 2), 3), round(float((lo[1] + hi[1]) / 2), 3)),
            area_mm2=round(area, 3),
            width_mm=round(width, 3),
            depth_mm=round(depth, 3),
            corner_radius_mm=round(corner_radius, 2) if corner_radius else None,
            chamfer_mm=round(chamfer, 2) if chamfer else None,
        )

    simplified = _simplify_ring(ring, tolerance)
    scale = tolerance
    while len(simplified) > MAX_POLYGON_POINTS:
        scale *= 1.5
        simplified = _simplify_ring(ring, scale)
    return Loop(
        kind="polygon",
        centre_mm=(round(float(centre[0]), 3), round(float(centre[1]), 3)),
        area_mm2=round(area, 3),
        points_mm=[(round(float(x), 3), round(float(y), 3)) for x, y in simplified],
    )


def _rectangle_corners(
    ring: np.ndarray, lo: np.ndarray, hi: np.ndarray, tolerance: float
) -> tuple[float, float] | None:
    """(corner_radius, chamfer) when every point lies on the bounding box or in a corner
    region that is round or cut at 45°; None when the ring is not a rectangle."""
    width, depth = float(hi[0] - lo[0]), float(hi[1] - lo[1])
    if width < 4 * tolerance or depth < 4 * tolerance:
        return None
    on_x = np.minimum(np.abs(ring[:, 0] - lo[0]), np.abs(ring[:, 0] - hi[0])) <= tolerance
    on_y = np.minimum(np.abs(ring[:, 1] - lo[1]), np.abs(ring[:, 1] - hi[1])) <= tolerance
    on_box = on_x | on_y
    if on_box.all():
        # a sharp rectangle needs its four corners to be there
        corners = [(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])]
        if all(np.hypot(*(ring - c).T).min() <= 2 * tolerance for c in corners):
            return (0.0, 0.0)
        return None
    off = ring[~on_box]
    deficit = width * depth - _area(ring)
    if deficit <= 0:
        return None
    radius = math.sqrt(deficit / (4 - math.pi))
    chamfer = math.sqrt(deficit / 2)
    limit = min(width, depth) / 2
    if radius > limit and chamfer > limit:
        return None
    # every off-box point must sit in a corner square and on the corner's arc or cut line
    corner_xy = np.array([(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])])
    inward = np.array([(1, 1), (-1, 1), (-1, -1), (1, -1)], dtype=float)
    nearest = np.argmin(np.stack([np.hypot(*(off - c).T) for c in corner_xy], axis=1), axis=1)
    local = (off - corner_xy[nearest]) * inward[nearest]  # (u, v) ≥ 0 into the part
    fillet_err = np.abs(np.hypot(*(local - radius).T) - radius)
    chamfer_err = np.abs(local.sum(axis=1) - chamfer) / math.sqrt(2)
    in_square = (local <= max(radius, chamfer) + tolerance).all(axis=1)
    if not in_square.all():
        return None
    if np.percentile(fillet_err, 95) <= 1.5 * tolerance and radius >= tolerance:
        return (radius, 0.0)
    if np.percentile(chamfer_err, 95) <= 1.5 * tolerance and chamfer >= tolerance:
        return (0.0, chamfer)
    return None


def _same_loop(a: Loop, b: Loop, tolerance: float) -> bool:
    if a.kind != b.kind:
        return False
    if math.hypot(a.centre_mm[0] - b.centre_mm[0], a.centre_mm[1] - b.centre_mm[1]) > 3 * tolerance:
        return False
    big = max(a.area_mm2, b.area_mm2, 1e-9)
    return abs(a.area_mm2 - b.area_mm2) / big <= 0.03


def _match_sets(a: list[Loop], b: list[Loop], tolerance: float) -> bool:
    if len(a) != len(b):
        return False
    used: set[int] = set()
    for loop in a:
        hit = next(
            (
                j
                for j, other in enumerate(b)
                if j not in used and _same_loop(loop, other, tolerance)
            ),
            None,
        )
        if hit is None:
            return False
        used.add(hit)
    return True


# --- slicing ----------------------------------------------------------------------------------


class _Slice:
    def __init__(self, z: float, rings: list[np.ndarray], tolerance: float) -> None:
        self.z = z
        self.outer: list[Loop] = []
        self.holes: list[Loop] = []
        self.rings_outer: list[np.ndarray] = []
        self.rings_holes: list[np.ndarray] = []
        # nesting depth by point-in-polygon: even = material outline, odd = hole
        depth = []
        for i, ring in enumerate(rings):
            d = sum(1 for j, other in enumerate(rings) if j != i and _contains(other, ring[0]))
            depth.append(d)
        for ring, d in zip(rings, depth, strict=True):
            if _area(ring) < (tolerance * 2) ** 2:
                continue  # a sliver from a face grazing the plane
            loop = _describe_loop(ring, tolerance)
            if d % 2 == 0:
                self.outer.append(loop)
                self.rings_outer.append(ring)
            else:
                self.holes.append(loop)
                self.rings_holes.append(ring)

    def signature_matches(self, other: _Slice, tolerance: float) -> bool:
        return _match_sets(self.outer, other.outer, tolerance) and _match_sets(
            self.holes, other.holes, tolerance
        )


def _slices(
    mesh: trimesh.Trimesh, axis: int, heights: np.ndarray, tolerance: float
) -> list[_Slice]:
    normal = np.zeros(3)
    normal[axis] = 1.0
    lines, _, _ = trimesh.intersections.mesh_multiplane(  # type: ignore[no-untyped-call]
        mesh, np.zeros(3), normal, heights
    )
    out = []
    for z, segs in zip(heights, lines, strict=True):
        rings = _loops_from_segments(np.asarray(segs, dtype=float)) if len(segs) else []
        out.append(_Slice(float(z), rings, tolerance))
    return out


def _axis_score(mesh: trimesh.Trimesh, axis: int, tolerance: float) -> tuple[float, int]:
    """How prismatic the part is along `axis`: (share of slices that belong to no run of
    alike slices, number of runs). The extrusion axis has the fewest of both — a plate
    sliced across its thickness is one run; sliced along it, every slice differs."""
    lo, hi = mesh.bounds[0][axis], mesh.bounds[1][axis]
    span = hi - lo
    if span <= 0:
        return (math.inf, 99)
    levels = 16
    heights = lo + span * (np.arange(levels) + 0.5) / levels
    runs: list[list[_Slice]] = []
    for s in _slices(mesh, axis, heights, tolerance):
        if runs and runs[-1][-1].signature_matches(s, tolerance):
            runs[-1].append(s)
        else:
            runs.append([s])
    stable = [run for run in runs if len(run) >= 2 and run[0].outer]
    explained = sum(len(run) for run in stable)
    return (round((levels - explained) / levels, 3), len(stable))


# --- the frame ---------------------------------------------------------------------------------


def _canonical(mesh: trimesh.Trimesh, tolerance: float) -> tuple[trimesh.Trimesh, np.ndarray]:
    """The part in its own frame: OBB-aligned, the extrusion axis along Z, the larger flat
    face down (the way it would sit on a table), min corner at the origin."""
    obb = mesh.bounding_box_oriented
    to_box = np.linalg.inv(obb.primitive.transform)
    aligned = mesh.copy()
    aligned.apply_transform(to_box)
    extents = aligned.extents
    scores = [_axis_score(aligned, axis, tolerance) for axis in range(3)]
    z_axis = min(range(3), key=lambda a: (*scores[a], extents[a]))
    others = [a for a in range(3) if a != z_axis]
    x_axis = max(others, key=lambda a: extents[a])
    y_axis = next(a for a in others if a != x_axis)
    rotation = np.zeros((3, 3))
    rotation[0, x_axis] = 1.0
    rotation[1, y_axis] = 1.0
    rotation[2, z_axis] = 1.0
    if np.linalg.det(rotation) < 0:
        rotation[1] *= -1  # keep the frame right-handed
    permute = np.eye(4)
    permute[:3, :3] = rotation
    aligned.apply_transform(permute)
    # the bigger flat face goes to the bottom: a plate with a pocket opens upwards, a boss
    # stands on its base
    normals = aligned.face_normals
    areas = aligned.area_faces
    up = float(areas[normals[:, 2] > 0.95].sum())
    down = float(areas[normals[:, 2] < -0.95].sum())
    flip = np.eye(4)
    if up > down * 1.02:
        flip[1, 1] = -1.0  # 180° about X: y and z change sign, the frame stays right-handed
        flip[2, 2] = -1.0
        aligned.apply_transform(flip)
    shift = np.eye(4)
    shift[:3, 3] = -aligned.bounds[0]
    aligned.apply_transform(shift)
    return aligned, shift @ flip @ permute @ to_box


# --- bands and edges ---------------------------------------------------------------------------


def _bisect_boundary(
    mesh: trimesh.Trimesh, reference: _Slice, lo: float, hi: float, tolerance: float
) -> float:
    """The height between lo (looks like `reference`) and hi (does not) where it changes."""
    for _ in range(7):
        mid = (lo + hi) / 2
        (s,) = _slices(mesh, 2, np.array([mid]), tolerance)
        if s.signature_matches(reference, tolerance):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _edge_from_zone(
    zone: list[_Slice], stable: _Slice, where: Literal["top", "bottom"], height: float
) -> EdgeFeature | None:
    """A run of slices shrinking towards a face is a fillet or a chamfer on that face's edges."""
    if height <= 0 or not zone or not stable.outer:
        return None
    ref_area = sum(o.area_mm2 for o in stable.outer)
    r_ref = math.sqrt(ref_area / math.pi)
    # the inset at mid-height tells a round from a cut: a quarter circle has moved only
    # 13 % of its radius half-way up, a 45° chamfer half its distance
    mid = zone[len(zone) // 2]
    mid_area = sum(o.area_mm2 for o in mid.outer)
    if mid_area <= 0 or mid_area >= ref_area:
        return None
    inset = r_ref - math.sqrt(mid_area / math.pi)
    ratio = inset / height
    if ratio < 0.3:
        return EdgeFeature(kind="fillet", where=where, size_mm=round(height, 2))
    if 0.35 <= ratio <= 0.65:
        return EdgeFeature(kind="chamfer", where=where, size_mm=round(height, 2))
    return None


def _bands(
    mesh: trimesh.Trimesh, slices: list[_Slice], tolerance: float, height: float
) -> tuple[list[Band], EdgeFeature | None, EdgeFeature | None, int]:
    """Runs of alike slices become bands; lone slices at the ends become edge features."""
    runs: list[list[_Slice]] = []
    for s in slices:
        if runs and runs[-1][-1].signature_matches(s, tolerance):
            runs[-1].append(s)
        else:
            runs.append([s])
    stable = [run for run in runs if len(run) >= 2 and run[0].outer]
    if not stable:
        return [], None, None, len(slices)

    bands: list[Band] = []
    unexplained = 0
    bottom_edge: EdgeFeature | None = None
    top_edge: EdgeFeature | None = None
    first, last = stable[0], stable[-1]
    # lone slices below the first stable run / above the last one
    below = [s for s in slices if s.z < first[0].z]
    above = [s for s in slices if s.z > last[-1].z]
    if below:
        z_edge = _bisect_boundary(mesh, first[0], first[0].z, below[-1].z, tolerance)
        bottom_edge = _edge_from_zone(below, first[0], "bottom", z_edge)
        if bottom_edge is None:
            unexplained += len(below)
    if above:
        z_edge = _bisect_boundary(mesh, last[-1], last[-1].z, above[0].z, tolerance)
        top_edge = _edge_from_zone(above, last[-1], "top", height - z_edge)
        if top_edge is None:
            unexplained += len(above)

    boundaries: list[float] = [0.0]
    for a, b in zip(stable, stable[1:], strict=False):
        between = [s for s in slices if a[-1].z < s.z < b[0].z]
        unexplained += len(between)
        boundaries.append(_bisect_boundary(mesh, a[-1], a[-1].z, b[0].z, tolerance))
    boundaries.append(height)
    for run, z0, z1 in zip(stable, boundaries[:-1], boundaries[1:], strict=True):
        middle = run[len(run) // 2]
        bands.append(
            Band(
                z0_mm=round(z0, 3),
                z1_mm=round(z1, 3),
                outer=_averaged(run, "outer", middle, tolerance),
                holes=_averaged(run, "holes", middle, tolerance),
                levels=len(run),
            )
        )
    return bands, top_edge, bottom_edge, unexplained


def _averaged(run: list[_Slice], attr: str, middle: _Slice, tolerance: float) -> list[Loop]:
    """Circles averaged over the run (a scan's noise cancels); other loops from the middle."""
    out: list[Loop] = []
    for loop in getattr(middle, attr):
        if loop.kind != "circle":
            out.append(loop)
            continue
        twins = [
            other
            for s in run
            for other in getattr(s, attr)
            if other.kind == "circle" and _same_loop(loop, other, tolerance)
        ]
        out.append(
            Loop(
                kind="circle",
                centre_mm=(
                    round(float(np.mean([t.centre_mm[0] for t in twins])), 3),
                    round(float(np.mean([t.centre_mm[1] for t in twins])), 3),
                ),
                area_mm2=round(float(np.mean([t.area_mm2 for t in twins])), 3),
                diameter_mm=round(float(np.mean([t.diameter_mm or 0 for t in twins])), 3),
            )
        )
    return out


# --- holes along X and Y ----------------------------------------------------------------------


def _side_holes(mesh: trimesh.Trimesh, axis: int, tolerance: float, levels: int) -> list[Cylinder]:
    """Circles that keep their centre and diameter across slices along `axis` are holes
    bored along it — through when they span the part, blind when they open on one face."""
    lo, hi = mesh.bounds[0][axis], mesh.bounds[1][axis]
    span = hi - lo
    if span <= 2 * tolerance:
        return []
    heights = lo + span * (np.arange(levels) + 0.5) / levels
    slices = _slices(mesh, axis, heights, tolerance)
    tracks: list[dict[str, Any]] = []
    for s in slices:
        for loop in s.holes:
            if loop.kind != "circle" or loop.diameter_mm is None:
                continue
            track = next(
                (
                    t
                    for t in tracks
                    if t["open"]
                    and math.hypot(
                        t["centre"][0] - loop.centre_mm[0], t["centre"][1] - loop.centre_mm[1]
                    )
                    <= 3 * tolerance
                    and abs(t["diameter"] - loop.diameter_mm)
                    <= max(0.03 * t["diameter"], tolerance)
                ),
                None,
            )
            if track is None:
                tracks.append(
                    {
                        "centre": loop.centre_mm,
                        "diameter": loop.diameter_mm,
                        "levels": [s.z],
                        "diameters": [loop.diameter_mm],
                        "open": True,
                    }
                )
            else:
                track["levels"].append(s.z)
                track["diameters"].append(loop.diameter_mm)
        for t in tracks:  # a track that missed this slice is closed
            if t["open"] and t["levels"][-1] != s.z:
                t["open"] = False
    axis_name: Axis = ("x", "y", "z")[axis]
    step = span / levels
    out: list[Cylinder] = []
    for t in tracks:
        if len(t["levels"]) < 2:
            continue
        z_lo, z_hi = min(t["levels"]) - step / 2, max(t["levels"]) + step / 2
        at_lo, at_hi = z_lo <= lo + step, z_hi >= hi - step
        through = at_lo and at_hi
        centre3 = [0.0, 0.0, 0.0]
        # the slice's 2D frame is the other two axes in order; put the axis coordinate back
        u, v = [a for a in range(3) if a != axis]
        centre3[u], centre3[v] = t["centre"][0], t["centre"][1]
        centre3[axis] = float(lo if through or at_lo else z_lo)
        length = float(span if through else z_hi - z_lo)
        out.append(
            Cylinder(
                kind="hole",
                axis=axis_name,
                centre_mm=(round(centre3[0], 3), round(centre3[1], 3), round(centre3[2], 3)),
                diameter_mm=round(float(np.mean(t["diameters"])), 3),
                length_mm=round(length, 3),
                through=through,
                from_face="inside"
                if not (at_lo or at_hi)
                else ("-" if at_lo and not at_hi else "+"),
                confidence=round(min(1.0, len(t["levels"]) / 4), 2),
            )
        )
    return out


# --- threads, symmetry, patterns --------------------------------------------------------------


def _radius_profile(
    mesh: trimesh.Trimesh, cylinder: Cylinder, step_mm: float
) -> tuple[np.ndarray, np.ndarray]:
    axis = _AXIS_INDEX[cylinder.axis]
    u, v = [a for a in range(3) if a != axis]
    start = cylinder.centre_mm[axis]
    count = int(min(400, max(8, cylinder.length_mm / step_mm)))
    heights = start + (np.arange(count) + 0.5) * (cylinder.length_mm / count)
    normal = np.zeros(3)
    normal[axis] = 1.0
    lines, _, _ = trimesh.intersections.mesh_multiplane(  # type: ignore[no-untyped-call]
        mesh, np.zeros(3), normal, heights
    )
    centre = np.array([cylinder.centre_mm[u], cylinder.centre_mm[v]])
    radii = []
    for segs in lines:
        if len(segs) == 0:
            radii.append(np.nan)
            continue
        pts = np.asarray(segs, dtype=float).reshape(-1, 2)
        d = np.hypot(*(pts - centre).T)
        near = d[d <= cylinder.diameter_mm * 0.75]
        radii.append(float(near.mean()) if len(near) else np.nan)
    return heights, np.array(radii)


def _thread_of(mesh: trimesh.Trimesh, cylinder: Cylinder) -> Thread | None:
    if cylinder.length_mm < 2.0 or cylinder.diameter_mm < 1.4:
        return None
    heights, radii = _radius_profile(mesh, cylinder, step_mm=0.05)
    good = ~np.isnan(radii)
    if good.sum() < 16:
        return None
    r = radii[good]
    h = heights[good]
    ripple = float(r.max() - r.min())
    if ripple < 0.04 or ripple < 0.01 * cylinder.diameter_mm:
        return None
    detrended = r - np.polyval(np.polyfit(h, r, 1), h)
    spectrum = np.abs(np.fft.rfft(detrended - detrended.mean()))
    freqs = np.fft.rfftfreq(len(detrended), d=float(np.mean(np.diff(h))))
    spectrum[0] = 0.0
    peak = int(np.argmax(spectrum))
    if freqs[peak] <= 0:
        return None
    pitch = 1.0 / float(freqs[peak])
    cycles = cylinder.length_mm / pitch
    if cycles < 2.5 or spectrum[peak] < 4 * float(np.median(spectrum[1:]) + 1e-9):
        return None
    major = 2 * float(r.max())
    minor = 2 * float(r.min())
    nominal = major if cylinder.kind == "hole" else major
    best = min(ISO_COARSE_PITCH_MM, key=lambda m: abs(m - nominal))
    standard = abs(best - nominal) <= max(0.4, 0.06 * best) and (
        abs(ISO_COARSE_PITCH_MM[best] - pitch) <= 0.12 * ISO_COARSE_PITCH_MM[best]
    )
    return Thread(
        on="hole" if cylinder.kind == "hole" else "boss",
        axis=cylinder.axis,
        centre_mm=cylinder.centre_mm,
        major_diameter_mm=round(major, 2),
        minor_diameter_mm=round(minor, 2),
        pitch_mm=round(pitch, 3),
        designation=f"M{best:g}x{ISO_COARSE_PITCH_MM[best]:g}" if standard else None,
        confidence=0.9 if standard else 0.5,
    )


def _ring_lands(moved: np.ndarray, targets: list[np.ndarray], limit: float) -> bool:
    """Does a transformed ring lie on one of the target rings, point for point?"""
    from scipy.spatial import cKDTree

    for target in targets:
        if len(target) < 3:
            continue
        distance, _ = cKDTree(target).query(moved, k=1)
        if float(np.percentile(distance, 95)) <= limit:
            return True
    return False


def _slice_maps_onto(moved: _Slice, target: _Slice, transform: Any, limit: float) -> bool:
    """Every ring of `moved`, transformed, lands on a ring of `target` of the same role."""
    for rings, others in (
        (moved.rings_outer, target.rings_outer),
        (moved.rings_holes, target.rings_holes),
    ):
        if len(rings) != len(others):
            return False
        for ring in rings:
            if not _ring_lands(transform(ring), others, limit):
                return False
    return True


def _symmetry(
    slices: list[_Slice], extents: tuple[float, float, float], tolerance: float
) -> Symmetry:
    """Mirror planes through the part's centre and n-fold rotation about Z, read off the
    slices: a symmetric part's outlines land on themselves after the transform."""
    cx, cy = extents[0] / 2, extents[1] / 2
    limit = max(2 * tolerance, 0.005 * max(extents))
    present = [s for s in slices if s.outer]
    if not present:
        return Symmetry(mirror=[])
    # x, y: within each slice
    mirror: list[Axis] = []
    for axis, name in ((0, "x"), (1, "y")):
        centre = cx if axis == 0 else cy

        def mirrored(ring: np.ndarray, axis: int = axis, centre: float = centre) -> np.ndarray:
            out = ring.copy()
            out[:, axis] = 2 * centre - out[:, axis]
            return out

        if all(_slice_maps_onto(s, s, mirrored, limit) for s in present):
            mirror.append(name)  # type: ignore[arg-type]
    # z: slice i against slice n-1-i (the levels are evenly spaced within the height)
    n = len(slices)
    if all(
        _slice_maps_onto(slices[i], slices[n - 1 - i], lambda ring: ring, limit)
        for i in range(n // 2 + 1)
    ):
        mirror.append("z")

    def rotated_by(angle: float) -> Any:
        c, si = math.cos(angle), math.sin(angle)

        def rotate(ring: np.ndarray) -> np.ndarray:
            rel = ring - np.array([cx, cy])
            out = np.empty_like(rel)
            out[:, 0] = c * rel[:, 0] - si * rel[:, 1]
            out[:, 1] = si * rel[:, 0] + c * rel[:, 1]
            return np.asarray(out + np.array([cx, cy]))

        return rotate

    order: int | None = None
    for k in (2, 3, 4, 5, 6, 8, 12):
        if all(_slice_maps_onto(s, s, rotated_by(2 * math.pi / k), limit) for s in present):
            order = k
    axisymmetric = order == 12 and all(
        _slice_maps_onto(s, s, rotated_by(2 * math.pi / 7), limit) for s in present
    )
    return Symmetry(mirror=mirror, rotational_order=order, axisymmetric=axisymmetric)


def _patterns(holes: list[Cylinder], tolerance: float) -> list[Pattern]:
    out: list[Pattern] = []
    vertical = [h for h in holes if h.axis == "z" and h.kind == "hole"]
    groups: list[list[Cylinder]] = []
    for hole in sorted(vertical, key=lambda h: h.diameter_mm):
        for group in groups:
            if abs(group[0].diameter_mm - hole.diameter_mm) <= max(0.03 * hole.diameter_mm, 0.1):
                group.append(hole)
                break
        else:
            groups.append([hole])
    for group in groups:
        if len(group) < 3:
            continue
        centres = np.array([[h.centre_mm[0], h.centre_mm[1]] for h in group])
        diameter = float(np.mean([h.diameter_mm for h in group]))
        # a line: every centre on the line through the two farthest apart, equal spacing
        d = np.hypot(*(centres[:, None, :] - centres[None, :, :]).transpose(2, 0, 1))
        i, j = np.unravel_index(int(np.argmax(d)), d.shape)
        direction = centres[j] - centres[i]
        length = float(np.hypot(*direction))
        if length > 0:
            unit = direction / length
            rel = centres - centres[i]
            offsets = np.abs(unit[0] * rel[:, 1] - unit[1] * rel[:, 0])
            along = np.sort((centres - centres[i]) @ unit)
            gaps = np.diff(along)
            if (
                offsets.max() <= 3 * tolerance
                and gaps.min() > 0
                and ((gaps.max() - gaps.min()) <= max(3 * tolerance, 0.03 * gaps.mean()))
            ):
                out.append(
                    Pattern(
                        kind="linear",
                        count=len(group),
                        diameter_mm=round(diameter, 3),
                        pitch_mm=round(float(gaps.mean()), 3),
                        centre_mm=(
                            round(float(centres[:, 0].mean()), 3),
                            round(float(centres[:, 1].mean()), 3),
                        ),
                    )
                )
                continue
        # a grid: the centres fill columns x rows with one pitch each way
        grid = _grid_of(centres, tolerance)
        if grid is not None:
            columns, rows, pitch_x, pitch_y = grid
            out.append(
                Pattern(
                    kind="grid",
                    count=len(group),
                    diameter_mm=round(diameter, 3),
                    centre_mm=(
                        round(float(centres[:, 0].mean()), 3),
                        round(float(centres[:, 1].mean()), 3),
                    ),
                    columns=columns,
                    rows=rows,
                    pitch_x_mm=round(pitch_x, 3),
                    pitch_y_mm=round(pitch_y, 3),
                )
            )
            continue
        # a circle: equal distance from the centroid, equal angular steps
        centroid = centres.mean(axis=0)
        radii = np.hypot(*(centres - centroid).T)
        if radii.mean() > 3 * tolerance and (radii.max() - radii.min()) <= 3 * tolerance:
            angles = np.sort(np.arctan2(*(centres - centroid).T[::-1]))
            steps = np.diff(np.concatenate([angles, [angles[0] + 2 * math.pi]]))
            if (steps.max() - steps.min()) <= math.radians(3):
                out.append(
                    Pattern(
                        kind="circular",
                        count=len(group),
                        diameter_mm=round(diameter, 3),
                        pitch_deg=round(float(np.degrees(steps.mean())), 2),
                        centre_mm=(round(float(centroid[0]), 3), round(float(centroid[1]), 3)),
                        radius_mm=round(float(radii.mean()), 3),
                    )
                )
    return out


def _distinct(values: np.ndarray, tolerance: float) -> list[float]:
    out: list[float] = []
    for v in np.sort(values):
        if not out or v - out[-1] > 3 * tolerance:
            out.append(float(v))
    return out


def _grid_of(centres: np.ndarray, tolerance: float) -> tuple[int, int, float, float] | None:
    xs = _distinct(centres[:, 0], tolerance)
    ys = _distinct(centres[:, 1], tolerance)
    if len(xs) < 2 or len(ys) < 2 or len(xs) * len(ys) != len(centres):
        return None
    for values in (xs, ys):
        gaps = np.diff(values)
        if (gaps.max() - gaps.min()) > max(3 * tolerance, 0.03 * gaps.mean()):
            return None
    # every lattice point must be occupied
    for x in xs:
        for y in ys:
            if not np.any(np.hypot(centres[:, 0] - x, centres[:, 1] - y) <= 3 * tolerance):
                return None
    return len(xs), len(ys), float(np.mean(np.diff(xs))), float(np.mean(np.diff(ys)))


def _planes(mesh: trimesh.Trimesh, limit: int = 12) -> list[Plane]:
    """Coplanar groups of faces, largest first — the faces a square would find."""
    try:
        facets = mesh.facets
        normals = mesh.facets_normal
        areas = mesh.facets_area
    except Exception:  # noqa: BLE001 — degenerate meshes have no facets
        return []
    total = float(mesh.area) or 1.0
    order = np.argsort(-np.asarray(areas))
    out: list[Plane] = []
    for idx in order[:limit]:
        area = float(areas[idx])
        if area < 0.005 * total:
            break
        normal = np.asarray(normals[idx], dtype=float)
        point = mesh.vertices[mesh.faces[facets[idx][0]][0]]
        out.append(
            Plane(
                normal=(
                    round(float(normal[0]), 4),
                    round(float(normal[1]), 4),
                    round(float(normal[2]), 4),
                ),
                offset_mm=round(float(np.dot(normal, point)), 3),
                area_mm2=round(area, 2),
            )
        )
    return out


# --- the whole thing --------------------------------------------------------------------------


def recognize(mesh: trimesh.Trimesh, request: FeatureRequest) -> FeatureReport:
    tol = request.tolerance_mm
    if len(mesh.faces) < 4:
        return FeatureReport(ok=False, message="the mesh has too few faces to read")
    part, transform = _canonical(mesh, tol)
    ex, ey, ez = (round(float(v), 3) for v in part.extents)
    extents: tuple[float, float, float] = (ex, ey, ez)
    height = float(part.extents[2])
    warnings: list[str] = []
    if not part.is_watertight:
        warnings.append("the mesh is not closed; slices through gaps are ignored")

    # holes bored from the sides first, so the Z slices can ignore their footprints
    side_holes = [
        h
        for axis in (0, 1)
        for h in _side_holes(part, axis, tol, levels=min(request.max_levels, 48))
    ]

    levels = int(min(request.max_levels, max(8, round(height / (2 * tol)))))
    heights = (np.arange(levels) + 0.5) * height / levels
    slices = _slices(part, 2, heights, tol)
    for s in slices:  # a side hole crossing a slice is a non-circular hole loop: not a band change
        keep_h, keep_r = [], []
        for loop, ring in zip(s.holes, s.rings_holes, strict=True):
            explained = any(_inside_side_hole(loop, h, s.z, tol) for h in side_holes)
            if not explained:
                keep_h.append(loop)
                keep_r.append(ring)
        s.holes, s.rings_holes = keep_h, keep_r
    bands, top_edge, bottom_edge, unexplained = _bands(part, slices, tol, height)
    if not bands:
        return FeatureReport(
            ok=False,
            message="no two slices of the part look alike: nothing prismatic to rebuild",
            faces=len(mesh.faces),
            watertight=bool(part.is_watertight),
            extents_mm=extents,
            planes=_planes(part),
            warnings=warnings,
        )

    cylinders: list[Cylinder] = list(side_holes)
    base = bands[0]
    if len(base.outer) == 1 and base.outer[0].kind == "circle" and base.outer[0].diameter_mm:
        cylinders.append(
            Cylinder(
                kind="body",
                axis="z",
                centre_mm=(*base.outer[0].centre_mm, base.z0_mm),
                diameter_mm=base.outer[0].diameter_mm,
                length_mm=round(base.z1_mm - base.z0_mm, 3),
                through=False,
                confidence=1.0,
            )
        )
    for band in bands[1:]:
        for loop in band.outer:
            if loop.kind == "circle" and loop.diameter_mm:
                cylinders.append(
                    Cylinder(
                        kind="boss",
                        axis="z",
                        centre_mm=(*loop.centre_mm, band.z0_mm),
                        diameter_mm=loop.diameter_mm,
                        length_mm=round(band.z1_mm - band.z0_mm, 3),
                        through=False,
                        confidence=round(min(1.0, band.levels / 3), 2),
                    )
                )
    cylinders.extend(_vertical_holes(bands, height, tol))

    threads: list[Thread] = []
    if request.threads:
        for cylinder in cylinders:
            if cylinder.kind == "body":
                continue
            found = _thread_of(part, cylinder)
            if found is not None:
                threads.append(found)

    edges: list[EdgeFeature] = []
    for loop in base.outer:
        if loop.kind == "rectangle" and loop.corner_radius_mm:
            edges.append(
                EdgeFeature(kind="fillet", where="vertical", size_mm=loop.corner_radius_mm, count=4)
            )
        if loop.kind == "rectangle" and loop.chamfer_mm:
            edges.append(
                EdgeFeature(kind="chamfer", where="vertical", size_mm=loop.chamfer_mm, count=4)
            )
    for edge in (top_edge, bottom_edge):
        if edge is not None:
            edges.append(edge)

    total_levels = len(slices)
    fidelity: Literal["prismatic", "stepped", "freeform"]
    if unexplained > 0.2 * total_levels or len(bands) > 8:
        fidelity = "freeform"
        warnings.append(
            "the outline changes continuously along the part: a stack of extrusions will only "
            "approximate it"
        )
    elif len(bands) == 1:
        fidelity = "prismatic"
    else:
        fidelity = "stepped"

    report = FeatureReport(
        ok=True,
        faces=len(mesh.faces),
        watertight=bool(part.is_watertight),
        extents_mm=extents,
        planes=_planes(part),
        cylinders=cylinders,
        edges=edges,
        threads=threads,
        symmetry=_symmetry(slices, extents, tol),
        patterns=_patterns(cylinders, tol),
        reconstruction=Reconstruction(
            frame_transform=[round(float(v), 6) for v in transform.reshape(-1)],
            extents_mm=extents,
            bands=bands,
            top_edge=top_edge,
            bottom_edge=bottom_edge,
            side_holes=side_holes,
            fidelity=fidelity,
            levels=total_levels,
            unexplained_levels=unexplained,
        ),
        warnings=warnings,
    )
    return report


def _inside_side_hole(loop: Loop, hole: Cylinder, z: float, tolerance: float) -> bool:
    """Does a Z-slice loop lie where a hole bored along X or Y crosses that slice?"""
    axis = _AXIS_INDEX[hole.axis]
    r = hole.diameter_mm / 2
    if abs(z - hole.centre_mm[2]) > r + tolerance:
        return False
    other = 1 - axis  # the in-plane axis across the hole
    along_lo = hole.centre_mm[axis]
    along_hi = along_lo + hole.length_mm
    c = loop.centre_mm
    across_ok = abs(c[other] - hole.centre_mm[other]) <= r + tolerance
    along_ok = along_lo - tolerance <= c[axis] <= along_hi + tolerance
    return across_ok and along_ok


def _vertical_holes(bands: list[Band], height: float, tolerance: float) -> list[Cylinder]:
    """Circular hole loops tracked through consecutive bands: through, blind or inside."""
    out: list[Cylinder] = []
    open_tracks: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    for band in bands:
        matched: set[int] = set()
        for loop in band.holes:
            if loop.kind != "circle" or loop.diameter_mm is None:
                continue
            track = next(
                (
                    t
                    for i, t in enumerate(open_tracks)
                    if i not in matched and _same_loop(t["loop"], loop, tolerance)
                ),
                None,
            )
            if track is None:
                open_tracks.append(
                    {"loop": loop, "z0": band.z0_mm, "z1": band.z1_mm, "d": [loop.diameter_mm]}
                )
                matched.add(len(open_tracks) - 1)
            else:
                track["z1"] = band.z1_mm
                track["d"].append(loop.diameter_mm)
                matched.add(open_tracks.index(track))
        still = []
        for i, t in enumerate(open_tracks):
            if i in matched:
                still.append(t)
            else:
                done.append(t)
        open_tracks = still
    done.extend(open_tracks)
    for t in done:
        tracked: Loop = t["loop"]
        at_bottom = t["z0"] <= tolerance
        at_top = t["z1"] >= height - tolerance
        out.append(
            Cylinder(
                kind="hole",
                axis="z",
                centre_mm=(tracked.centre_mm[0], tracked.centre_mm[1], round(float(t["z0"]), 3)),
                diameter_mm=round(float(np.mean(t["d"])), 3),
                length_mm=round(float(t["z1"] - t["z0"]), 3),
                through=at_bottom and at_top,
                from_face="+" if at_top else ("-" if at_bottom else "inside"),
                confidence=1.0,
            )
        )
    return out


# --- deviation ---------------------------------------------------------------------------------


def deviation(
    scan: trimesh.Trimesh,
    rebuilt: trimesh.Trimesh,
    transform: np.ndarray,
    tolerance: float,
    samples: int = 3000,
) -> Deviation:
    """How far the rebuilt part is from the scan, both ways, in the part's frame."""
    placed = scan.copy()
    placed.apply_transform(transform)
    a, _ = trimesh.sample.sample_surface(placed, samples, seed=11)
    b, _ = trimesh.sample.sample_surface(rebuilt, samples, seed=11)
    to_rebuilt = trimesh.proximity.ProximityQuery(rebuilt)  # type: ignore[no-untyped-call]
    to_scan = trimesh.proximity.ProximityQuery(placed)  # type: ignore[no-untyped-call]
    _, d_ab, _ = to_rebuilt.on_surface(a)
    _, d_ba, _ = to_scan.on_surface(b)
    d = np.concatenate([d_ab, d_ba])
    return Deviation(
        ok=True,
        tolerance_mm=tolerance,
        mean_mm=round(float(d.mean()), 3),
        p95_mm=round(float(np.percentile(d, 95)), 3),
        max_mm=round(float(d.max()), 3),
        within_tolerance=round(float((d <= tolerance).mean()), 3),
        samples=int(len(d)),
    )


# --- files and the sandbox ---------------------------------------------------------------------


def _load(source: Path, source_format: str) -> trimesh.Trimesh | None:
    loaded = trimesh.load(
        io.BytesIO(source.read_bytes()),
        file_type=source_format,
        force="mesh" if source_format in ("stl", "obj", "ply") else "scene",
        process=False,
    )
    mesh = as_single_mesh(loaded)
    if mesh is None:
        return None
    mesh = to_platform_axes(mesh.copy(), source_format)
    mesh.merge_vertices()
    return mesh


def recognize_file(source: Path, source_format: str, request: FeatureRequest) -> FeatureReport:
    mesh = _load(source, source_format)
    if mesh is None:
        return FeatureReport(ok=False, message="the file has no mesh to read")
    return recognize(mesh, request)


def deviation_file(
    scan: Path, scan_format: str, rebuilt: Path, transform: list[float], tolerance: float
) -> Deviation:
    a = _load(scan, scan_format)
    b = _load(rebuilt, "stl")
    if a is None or b is None:
        return Deviation(ok=False, message="a mesh is missing")
    return deviation(a, b, np.array(transform, dtype=float).reshape(4, 4), tolerance)


def recognize_in_sandbox(
    source: Path, source_format: str, request: FeatureRequest, limits: Any | None = None
) -> FeatureReport:
    from worker import sandbox

    outcome = sandbox.run(
        "worker.features",
        ["recognize", source_format, str(source), request.model_dump_json()],
        input_path=source,
        limits=limits or sandbox.DEFAULT_LIMITS,
    )
    if not outcome.ok:
        return FeatureReport(ok=False, message=outcome.message)
    return FeatureReport.model_validate(outcome.output)


def deviation_in_sandbox(
    scan: Path,
    scan_format: str,
    rebuilt: Path,
    transform: list[float],
    tolerance: float,
    limits: Any | None = None,
) -> Deviation:
    from worker import sandbox

    outcome = sandbox.run(
        "worker.features",
        [
            "deviation",
            scan_format,
            str(scan),
            str(rebuilt),
            json.dumps({"transform": transform, "tolerance_mm": tolerance}),
        ],
        input_path=scan,
        limits=limits or sandbox.DEFAULT_LIMITS,
    )
    if not outcome.ok:
        return Deviation(ok=False, message=outcome.message)
    return Deviation.model_validate(outcome.output)


if __name__ == "__main__":  # sandbox child
    import sys

    mode = sys.argv[1]
    try:
        if mode == "recognize":
            source_format, source_path, payload = sys.argv[2:5]
            result: BaseModel = recognize_file(
                Path(source_path), source_format, FeatureRequest.model_validate_json(payload)
            )
        else:
            scan_format, scan_path, rebuilt_path, payload = sys.argv[2:6]
            options = json.loads(payload)
            result = deviation_file(
                Path(scan_path),
                scan_format,
                Path(rebuilt_path),
                options["transform"],
                float(options.get("tolerance_mm", 0.2)),
            )
        print(json.dumps(result.model_dump(mode="json")))
    except Exception as exc:  # the parent turns this into a typed failure
        print(json.dumps({"ok": False, "message": f"{type(exc).__name__}: {exc}"}))
        sys.exit(1)
