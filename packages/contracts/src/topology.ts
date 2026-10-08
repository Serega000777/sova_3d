/**
 * Real mesh topology for the studio overlay (T-234, F-086).
 *
 * A viewer holds triangles; a person selects vertices, edges and faces. This module builds
 * the indexed topology those selections refer to, from plain typed arrays, so web, desktop
 * and mobile agree on what "vertex 12" or "edge 40" means. STL stores every triangle with
 * its own three corners, so positions are welded first; the weld map keeps every selection
 * resolvable back to the original triangle corners.
 */
import type { Axis, Profile, Vec3 } from "./operation-plan.js";

export type ComponentKind = "vertex" | "edge" | "face";
export type SelectMode = "replace" | "add" | "remove" | "toggle";

/** Why a topology can or cannot be trusted for component editing. */
export type TopologyStatus =
  /** Indexed, closed, every edge shared by exactly two faces. */
  | "stable"
  /** Usable, but with open boundaries or non-manifold edges worth showing the person. */
  | "open"
  /** No triangles, or too few after welding; component selection is unavailable. */
  | "none";

export interface TopologyReport {
  status: TopologyStatus;
  /** True when the source brought its own index buffer (GLB); false for unindexed STL. */
  sourceIndexed: boolean;
  vertices: number;
  edges: number;
  faces: number;
  /** Corners merged by the weld, i.e. source corners minus welded vertices. */
  weldedCorners: number;
  boundaryEdges: number;
  nonManifoldEdges: number;
  degenerateFaces: number;
}

export interface MeshTopology {
  /** Welded vertex positions, xyz per vertex, in the mesh's own units. */
  positions: Float32Array;
  /** Triangle corners as welded vertex ids, 3 per face. Degenerate faces are dropped. */
  faces: Uint32Array;
  /** Unique edges as welded vertex ids, 2 per edge, lower id first. */
  edges: Uint32Array;
  /** For each edge, the faces that use it (first two; non-manifold edges keep the count). */
  edgeFaces: Int32Array;
  /** How many faces share each edge. */
  edgeUse: Uint8Array;
  /** For each kept face, its index among the source triangles. */
  sourceFace: Uint32Array;
  /** For each source corner (3 per source triangle), its welded vertex id. */
  cornerVertex: Uint32Array;
  report: TopologyReport;
}

/** A planar mesh-face selection converted into an exact, editable CAD sketch frame. */
export interface CadProfileSeed {
  profile: Extract<Profile, { kind: "sketch" }>;
  origin_mm: Vec3;
  normal: Vec3;
  x_direction: Vec3;
  source_faces: number;
}

export type CadProfileFailureCode =
  | "selection_empty"
  | "selection_too_large"
  | "face_missing"
  | "selection_disconnected"
  | "selection_non_planar"
  | "selection_non_manifold"
  | "selection_has_holes"
  | "selection_open_boundary"
  | "profile_too_small"
  | "profile_too_complex";

export type CadProfileResult =
  | { ok: true; seed: CadProfileSeed }
  | { ok: false; code: CadProfileFailureCode };

/** Edges beyond this are not all drawn while a person is interacting; selection stays exact. */
export const INTERACTION_EDGE_BUDGET = 60_000;

export interface BuildOptions {
  /** Corners closer than this (mesh units) are one vertex. Default 1e-4. */
  tolerance?: number;
  /** Whether the source supplied an index buffer. */
  sourceIndexed?: boolean;
}

/**
 * Welds positions and builds vertex/edge/face tables.
 * `index` is the source's triangle index buffer, or null for an unindexed triangle soup.
 */
export function buildTopology(
  positions: ArrayLike<number>,
  index: ArrayLike<number> | null,
  options: BuildOptions = {},
): MeshTopology {
  const tolerance = options.tolerance ?? 1e-4;
  const sourceIndexed = options.sourceIndexed ?? index !== null;
  const sourceVertexCount = Math.floor(positions.length / 3);
  const cornerCount = index ? Math.floor(index.length / 3) * 3 : Math.floor(sourceVertexCount / 3) * 3;
  const triangleCount = cornerCount / 3;

  const weldKey = new Map<string, number>();
  const sourceToWelded = new Int32Array(sourceVertexCount).fill(-1);
  const weldedPositions: number[] = [];
  const inverse = 1 / tolerance;
  const welded = (source: number): number => {
    const cached = sourceToWelded[source] ?? -1;
    if (cached >= 0) return cached;
    const x = positions[source * 3] ?? 0;
    const y = positions[source * 3 + 1] ?? 0;
    const z = positions[source * 3 + 2] ?? 0;
    const key = `${Math.round(x * inverse)},${Math.round(y * inverse)},${Math.round(z * inverse)}`;
    let id = weldKey.get(key);
    if (id === undefined) {
      id = weldedPositions.length / 3;
      weldedPositions.push(x, y, z);
      weldKey.set(key, id);
    }
    sourceToWelded[source] = id;
    return id;
  };

  const cornerVertex = new Uint32Array(cornerCount);
  const keptFaces: number[] = [];
  const keptSource: number[] = [];
  let degenerateFaces = 0;
  for (let t = 0; t < triangleCount; t += 1) {
    const sources = [0, 1, 2].map((c) => (index ? (index[t * 3 + c] ?? 0) : t * 3 + c));
    const ids = sources.map(welded);
    for (let c = 0; c < 3; c += 1) cornerVertex[t * 3 + c] = ids[c] as number;
    const [a, b, c] = ids as [number, number, number];
    if (a === b || b === c || a === c) {
      degenerateFaces += 1;
      continue;
    }
    keptFaces.push(a, b, c);
    keptSource.push(t);
  }

  const faces = Uint32Array.from(keptFaces);
  const faceCount = faces.length / 3;
  const edgeIndex = new Map<number, number>();
  const edgeList: number[] = [];
  const edgeFaceList: number[] = [];
  const edgeUseList: number[] = [];
  const vertexCount = weldedPositions.length / 3;
  for (let f = 0; f < faceCount; f += 1) {
    for (let c = 0; c < 3; c += 1) {
      const from = faces[f * 3 + c] as number;
      const to = faces[f * 3 + ((c + 1) % 3)] as number;
      const lo = Math.min(from, to);
      const hi = Math.max(from, to);
      const key = lo * vertexCount + hi; // exact below 2^53, i.e. ~94M vertices
      let edge = edgeIndex.get(key);
      if (edge === undefined) {
        edge = edgeList.length / 2;
        edgeIndex.set(key, edge);
        edgeList.push(lo, hi);
        edgeFaceList.push(f, -1);
        edgeUseList.push(1);
      } else {
        const used = edgeUseList[edge] as number;
        if (used === 1) edgeFaceList[edge * 2 + 1] = f;
        edgeUseList[edge] = Math.min(used + 1, 255);
      }
    }
  }

  const edgeUse = Uint8Array.from(edgeUseList);
  let boundaryEdges = 0;
  let nonManifoldEdges = 0;
  for (const used of edgeUse) {
    if (used === 1) boundaryEdges += 1;
    else if (used > 2) nonManifoldEdges += 1;
  }
  const status: TopologyStatus =
    faceCount < 1 ? "none" : boundaryEdges === 0 && nonManifoldEdges === 0 ? "stable" : "open";

  return {
    positions: Float32Array.from(weldedPositions),
    faces,
    edges: Uint32Array.from(edgeList),
    edgeFaces: Int32Array.from(edgeFaceList),
    edgeUse,
    sourceFace: Uint32Array.from(keptSource),
    cornerVertex,
    report: {
      status,
      sourceIndexed,
      vertices: vertexCount,
      edges: edgeUse.length,
      faces: faceCount,
      weldedCorners: Math.max(sourceVertexCount - vertexCount, 0),
      boundaryEdges,
      nonManifoldEdges,
      degenerateFaces,
    },
  };
}

/** One-line explanation for the UI, or null when selection is fully trustworthy. */
export function topologyNotice(report: TopologyReport, language: "en" | "ru"): string | null {
  const ru = language === "ru";
  if (report.status === "none") {
    return ru
      ? "У этого формата нет стабильной топологии: выбор вершин, рёбер и граней недоступен."
      : "This format has no stable topology: vertex, edge and face selection is unavailable.";
  }
  if (report.status === "open") {
    const parts: string[] = [];
    if (report.boundaryEdges > 0) parts.push(ru ? `открытых рёбер: ${report.boundaryEdges}` : `${report.boundaryEdges} open edges`);
    if (report.nonManifoldEdges > 0) {
      parts.push(ru ? `неманифолдных рёбер: ${report.nonManifoldEdges}` : `${report.nonManifoldEdges} non-manifold edges`);
    }
    return ru ? `Сетка не замкнута — ${parts.join(", ")}.` : `Mesh is not watertight — ${parts.join(", ")}.`;
  }
  if (!report.sourceIndexed) {
    return ru
      ? "Файл без индексов (STL): вершины объединены по позиции."
      : "Unindexed file (STL): vertices were merged by position.";
  }
  return null;
}

/** Combine a pick into the current selection set (ids are vertex, edge or face ids). */
export function applySelection(
  current: ReadonlySet<number>,
  picked: Iterable<number>,
  mode: SelectMode,
): Set<number> {
  const next = mode === "replace" ? new Set<number>() : new Set(current);
  for (const id of picked) {
    if (mode === "remove") next.delete(id);
    else if (mode === "toggle") {
      if (next.has(id)) next.delete(id);
      else next.add(id);
    } else next.add(id);
  }
  return next;
}

export interface PickHit {
  /** Source triangle index as the renderer reports it (Mesh raycast `faceIndex`). */
  sourceFace: number;
  /** Where the ray met the surface, in mesh units. */
  point: readonly [number, number, number];
}

function vertexAt(topology: MeshTopology, id: number): [number, number, number] {
  const p = topology.positions;
  return [p[id * 3] as number, p[id * 3 + 1] as number, p[id * 3 + 2] as number];
}

function distanceSquared(a: readonly number[], b: readonly number[]): number {
  const dx = (a[0] as number) - (b[0] as number);
  const dy = (a[1] as number) - (b[1] as number);
  const dz = (a[2] as number) - (b[2] as number);
  return dx * dx + dy * dy + dz * dz;
}

function segmentDistanceSquared(
  point: readonly number[],
  a: readonly number[],
  b: readonly number[],
): number {
  const abx = (b[0] as number) - (a[0] as number);
  const aby = (b[1] as number) - (a[1] as number);
  const abz = (b[2] as number) - (a[2] as number);
  const length = abx * abx + aby * aby + abz * abz;
  const t =
    length === 0
      ? 0
      : Math.max(
          0,
          Math.min(
            1,
            (((point[0] as number) - (a[0] as number)) * abx +
              ((point[1] as number) - (a[1] as number)) * aby +
              ((point[2] as number) - (a[2] as number)) * abz) /
              length,
          ),
        );
  return distanceSquared(point, [(a[0] as number) + abx * t, (a[1] as number) + aby * t, (a[2] as number) + abz * t]);
}

/** Map a source triangle to its kept face id, or -1 if it was dropped as degenerate. */
export function keptFaceOf(topology: MeshTopology, sourceFace: number): number {
  // sourceFace is ascending, so binary search.
  let lo = 0;
  let hi = topology.sourceFace.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const value = topology.sourceFace[mid] as number;
    if (value === sourceFace) return mid;
    if (value < sourceFace) lo = mid + 1;
    else hi = mid - 1;
  }
  return -1;
}

/**
 * The component of the requested kind a click means: the face it hit, the face's corner
 * nearest the point, or the face's edge nearest the point.
 */
export function componentAtHit(
  topology: MeshTopology,
  kind: ComponentKind,
  hit: PickHit,
): number | null {
  const face = keptFaceOf(topology, hit.sourceFace);
  if (face < 0) return null;
  if (kind === "face") return face;
  const corners = [0, 1, 2].map((c) => topology.faces[face * 3 + c] as number);
  if (kind === "vertex") {
    let best = corners[0] as number;
    let bestDistance = Infinity;
    for (const id of corners) {
      const distance = distanceSquared(hit.point, vertexAt(topology, id));
      if (distance < bestDistance) {
        best = id;
        bestDistance = distance;
      }
    }
    return best;
  }
  let bestEdge = -1;
  let bestDistance = Infinity;
  for (let c = 0; c < 3; c += 1) {
    const a = corners[c] as number;
    const b = corners[(c + 1) % 3] as number;
    const edge = edgeId(topology, a, b);
    if (edge < 0) continue;
    const distance = segmentDistanceSquared(hit.point, vertexAt(topology, a), vertexAt(topology, b));
    if (distance < bestDistance) {
      bestEdge = edge;
      bestDistance = distance;
    }
  }
  return bestEdge < 0 ? null : bestEdge;
}

/** Edge id joining two welded vertices, or -1. Linear in edges; use only for single picks. */
export function edgeId(topology: MeshTopology, a: number, b: number): number {
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  for (let e = 0; e < topology.edgeUse.length; e += 1) {
    if (topology.edges[e * 2] === lo && topology.edges[e * 2 + 1] === hi) return e;
  }
  return -1;
}

export interface ScreenRect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * Box selection. `screen` holds a projected x,y per welded vertex and `visible[i]` says
 * whether vertex i is in front of the camera and not hidden behind the surface.
 * Edges need both ends inside; faces need all three corners inside.
 */
export function selectInRect(
  topology: MeshTopology,
  kind: ComponentKind,
  screen: ArrayLike<number>,
  visible: ArrayLike<number | boolean>,
  rect: ScreenRect,
): number[] {
  const inside = (id: number): boolean => {
    if (!visible[id]) return false;
    const x = screen[id * 2] as number;
    const y = screen[id * 2 + 1] as number;
    return x >= rect.minX && x <= rect.maxX && y >= rect.minY && y <= rect.maxY;
  };
  const out: number[] = [];
  if (kind === "vertex") {
    for (let v = 0; v < topology.report.vertices; v += 1) if (inside(v)) out.push(v);
  } else if (kind === "edge") {
    for (let e = 0; e < topology.report.edges; e += 1) {
      if (inside(topology.edges[e * 2] as number) && inside(topology.edges[e * 2 + 1] as number)) out.push(e);
    }
  } else {
    for (let f = 0; f < topology.report.faces; f += 1) {
      if (
        inside(topology.faces[f * 3] as number) &&
        inside(topology.faces[f * 3 + 1] as number) &&
        inside(topology.faces[f * 3 + 2] as number)
      ) {
        out.push(f);
      }
    }
  }
  return out;
}

/** Vertices touched by a selection of any kind, deduplicated and ascending. */
export function verticesOf(topology: MeshTopology, kind: ComponentKind, ids: Iterable<number>): number[] {
  const set = new Set<number>();
  for (const id of ids) {
    if (kind === "vertex") set.add(id);
    else if (kind === "edge") {
      set.add(topology.edges[id * 2] as number);
      set.add(topology.edges[id * 2 + 1] as number);
    } else {
      for (let c = 0; c < 3; c += 1) set.add(topology.faces[id * 3 + c] as number);
    }
  }
  return [...set].sort((a, b) => a - b);
}

function cadSubtract(a: readonly number[], b: readonly number[]): Vec3 {
  return [
    (a[0] as number) - (b[0] as number),
    (a[1] as number) - (b[1] as number),
    (a[2] as number) - (b[2] as number),
  ];
}

function cadDot(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number)
    + (a[1] as number) * (b[1] as number)
    + (a[2] as number) * (b[2] as number);
}

function cadCross(a: readonly number[], b: readonly number[]): Vec3 {
  return [
    (a[1] as number) * (b[2] as number) - (a[2] as number) * (b[1] as number),
    (a[2] as number) * (b[0] as number) - (a[0] as number) * (b[2] as number),
    (a[0] as number) * (b[1] as number) - (a[1] as number) * (b[0] as number),
  ];
}

function cadNormalise(value: readonly number[]): Vec3 | null {
  const length = Math.hypot(value[0] as number, value[1] as number, value[2] as number);
  if (length <= 1e-12) return null;
  return [
    (value[0] as number) / length,
    (value[1] as number) / length,
    (value[2] as number) / length,
  ];
}

function cadLexicographic(a: readonly number[], b: readonly number[]): number {
  for (let axis = 0; axis < 3; axis += 1) {
    const difference = (a[axis] as number) - (b[axis] as number);
    if (Math.abs(difference) > 1e-12) return difference;
  }
  return 0;
}

/**
 * Turn one connected, planar face patch into a closed line sketch on its measured plane.
 * Interior triangulation edges and collinear boundary vertices disappear; holes, multiple
 * patches and non-planar selections fail closed instead of inventing a profile.
 */
export function cadProfileFromFaces(
  topology: MeshTopology,
  faceIds: Iterable<number>,
  toleranceMm = 1e-4,
): CadProfileResult {
  const selected = [...new Set(faceIds)].sort((a, b) => a - b);
  if (selected.length === 0) return { ok: false, code: "selection_empty" };
  if (selected.length > 10_000) return { ok: false, code: "selection_too_large" };
  if (selected.some((face) => !Number.isInteger(face) || face < 0 || face >= topology.report.faces)) {
    return { ok: false, code: "face_missing" };
  }

  const point = (vertex: number): Vec3 => vertexAt(topology, vertex);
  const faceVertices = (face: number): [number, number, number] => [
    topology.faces[face * 3] as number,
    topology.faces[face * 3 + 1] as number,
    topology.faces[face * 3 + 2] as number,
  ];
  const allVertices = verticesOf(topology, "face", selected);
  const boundsMin: Vec3 = [Infinity, Infinity, Infinity];
  const boundsMax: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const vertex of allVertices) {
    const p = point(vertex);
    for (let axis = 0; axis < 3; axis += 1) {
      boundsMin[axis] = Math.min(boundsMin[axis] as number, p[axis] as number);
      boundsMax[axis] = Math.max(boundsMax[axis] as number, p[axis] as number);
    }
  }
  const diagonal = Math.hypot(
    boundsMax[0] - boundsMin[0],
    boundsMax[1] - boundsMin[1],
    boundsMax[2] - boundsMin[2],
  );
  const tolerance = Math.max(toleranceMm, diagonal * 1e-6, 1e-7);

  const firstCorners = faceVertices(selected[0] as number).map(point) as [Vec3, Vec3, Vec3];
  let normal = cadNormalise(cadCross(
    cadSubtract(firstCorners[1], firstCorners[0]),
    cadSubtract(firstCorners[2], firstCorners[0]),
  ));
  if (!normal) return { ok: false, code: "profile_too_small" };
  const dominant = normal.reduce(
    (best, value, axis) => Math.abs(value) > Math.abs(normal?.[best] ?? 0) ? axis : best,
    0,
  );
  if ((normal[dominant] as number) < 0) normal = normal.map((value) => -value) as Vec3;
  const planeOrigin = firstCorners[0];

  for (const face of selected) {
    const corners = faceVertices(face).map(point) as [Vec3, Vec3, Vec3];
    const candidate = cadNormalise(cadCross(
      cadSubtract(corners[1], corners[0]),
      cadSubtract(corners[2], corners[0]),
    ));
    if (!candidate || Math.abs(cadDot(candidate, normal)) < 1 - 1e-6) {
      return { ok: false, code: "selection_non_planar" };
    }
    if (corners.some((corner) => Math.abs(cadDot(cadSubtract(corner, planeOrigin), normal)) > tolerance)) {
      return { ok: false, code: "selection_non_planar" };
    }
  }

  const edgeFaces = new Map<string, number[]>();
  const edgeEnds = new Map<string, [number, number]>();
  const globalEdgeUse = new Map<string, number>();
  for (let edge = 0; edge < topology.edgeUse.length; edge += 1) {
    globalEdgeUse.set(
      `${topology.edges[edge * 2]}:${topology.edges[edge * 2 + 1]}`,
      topology.edgeUse[edge] as number,
    );
  }
  for (const face of selected) {
    const corners = faceVertices(face);
    for (let side = 0; side < 3; side += 1) {
      const from = corners[side] as number;
      const to = corners[(side + 1) % 3] as number;
      const ends: [number, number] = [Math.min(from, to), Math.max(from, to)];
      const key = `${ends[0]}:${ends[1]}`;
      if ((globalEdgeUse.get(key) ?? 0) > 2) {
        return { ok: false, code: "selection_non_manifold" };
      }
      const uses = edgeFaces.get(key) ?? [];
      uses.push(face);
      edgeFaces.set(key, uses);
      edgeEnds.set(key, ends);
      if (uses.length > 2) return { ok: false, code: "selection_non_manifold" };
    }
  }

  const neighbours = new Map<number, Set<number>>();
  for (const faces of edgeFaces.values()) {
    if (faces.length !== 2) continue;
    const left = faces[0] as number;
    const right = faces[1] as number;
    const leftNeighbours = neighbours.get(left) ?? new Set<number>();
    const rightNeighbours = neighbours.get(right) ?? new Set<number>();
    leftNeighbours.add(right);
    rightNeighbours.add(left);
    neighbours.set(left, leftNeighbours);
    neighbours.set(right, rightNeighbours);
  }
  const reached = new Set<number>();
  const pending = [selected[0] as number];
  while (pending.length > 0) {
    const face = pending.pop() as number;
    if (reached.has(face)) continue;
    reached.add(face);
    for (const adjacent of neighbours.get(face) ?? []) pending.push(adjacent);
  }
  if (reached.size !== selected.length) return { ok: false, code: "selection_disconnected" };

  const boundary = [...edgeFaces.entries()]
    .filter(([, faces]) => faces.length === 1)
    .map(([key]) => edgeEnds.get(key) as [number, number]);
  if (boundary.length < 3) return { ok: false, code: "profile_too_small" };
  const boundaryAdjacency = new Map<number, number[]>();
  for (const [left, right] of boundary) {
    boundaryAdjacency.set(left, [...(boundaryAdjacency.get(left) ?? []), right]);
    boundaryAdjacency.set(right, [...(boundaryAdjacency.get(right) ?? []), left]);
  }
  if ([...boundaryAdjacency.values()].some((items) => items.length !== 2)) {
    return { ok: false, code: "selection_open_boundary" };
  }

  const boundaryVertices = [...boundaryAdjacency.keys()].sort((left, right) =>
    cadLexicographic(point(left), point(right)) || left - right,
  );
  const start = boundaryVertices[0] as number;
  const loop: number[] = [start];
  let previous = -1;
  let current = start;
  for (let step = 0; step <= boundary.length; step += 1) {
    const choices = boundaryAdjacency.get(current) as number[];
    const next = choices[0] === previous ? choices[1] as number : choices[0] as number;
    if (next === start) break;
    if (loop.includes(next)) return { ok: false, code: "selection_has_holes" };
    loop.push(next);
    previous = current;
    current = next;
  }
  if (loop.length !== boundary.length) return { ok: false, code: "selection_has_holes" };

  let outline = loop.map(point);
  let changed = true;
  while (changed && outline.length > 3) {
    changed = false;
    for (let index = 0; index < outline.length; index += 1) {
      const before = outline[(index + outline.length - 1) % outline.length] as Vec3;
      const here = outline[index] as Vec3;
      const after = outline[(index + 1) % outline.length] as Vec3;
      const incoming = cadSubtract(here, before);
      const outgoing = cadSubtract(after, here);
      const cross = cadCross(incoming, outgoing);
      const scale = Math.max(Math.hypot(...incoming), Math.hypot(...outgoing), 1);
      if (Math.hypot(...cross) <= tolerance * scale && cadDot(incoming, outgoing) > 0) {
        outline.splice(index, 1);
        changed = true;
        break;
      }
    }
  }
  if (outline.length < 3) return { ok: false, code: "profile_too_small" };
  if (outline.length > 128) return { ok: false, code: "profile_too_complex" };

  const referenceAxis: Vec3 = Math.abs(normal[0]) <= Math.abs(normal[1]) && Math.abs(normal[0]) <= Math.abs(normal[2])
    ? [1, 0, 0]
    : Math.abs(normal[1]) <= Math.abs(normal[2]) ? [0, 1, 0] : [0, 0, 1];
  const provisionalX = cadNormalise(cadCross(referenceAxis, normal)) as Vec3;
  const provisionalY = cadCross(normal, provisionalX);
  const projected = outline.map((item) => {
    const delta = cadSubtract(item, planeOrigin);
    return [cadDot(delta, provisionalX), cadDot(delta, provisionalY)] as const;
  });
  const twiceArea = projected.reduce((sum, item, index) => {
    const next = projected[(index + 1) % projected.length] as readonly [number, number];
    return sum + item[0] * next[1] - item[1] * next[0];
  }, 0);
  if (twiceArea < 0) outline = [outline[0] as Vec3, ...outline.slice(1).reverse()];

  let startIndex = 0;
  for (let index = 1; index < outline.length; index += 1) {
    if (cadLexicographic(outline[index] as Vec3, outline[startIndex] as Vec3) < 0) startIndex = index;
  }
  outline = [...outline.slice(startIndex), ...outline.slice(0, startIndex)];
  const origin = outline[0] as Vec3;
  const xDirection = cadNormalise(cadSubtract(outline[1] as Vec3, origin));
  if (!xDirection) return { ok: false, code: "profile_too_small" };
  const yDirection = cadCross(normal, xDirection);
  const points = outline.map((item) => {
    const delta = cadSubtract(item, origin);
    const x = cadDot(delta, xDirection);
    const y = cadDot(delta, yDirection);
    return [Math.abs(x) <= tolerance ? 0 : x, Math.abs(y) <= tolerance ? 0 : y] as [number, number];
  });

  return {
    ok: true,
    seed: {
      profile: {
        kind: "sketch",
        points_mm: points,
        segments: points.map(() => ({ kind: "line" as const })),
        constraints: [],
        tolerance_mm: Math.min(Math.max(tolerance, 1e-5), 0.1),
      },
      origin_mm: origin,
      normal,
      x_direction: xDirection,
      source_faces: selected.length,
    },
  };
}

/**
 * Edge ids worth drawing while interacting. At or under the budget it is every edge; over
 * it, open and non-manifold edges plus the sharpest creases first, then an even sample.
 * Selection never uses this list — it always resolves against the full topology.
 */
export function overlayEdges(topology: MeshTopology, budget = INTERACTION_EDGE_BUDGET): number[] {
  const total = topology.report.edges;
  if (total <= budget) return Array.from({ length: total }, (_, e) => e);
  const important: number[] = [];
  const rest: number[] = [];
  for (let e = 0; e < total; e += 1) {
    (topology.edgeUse[e] === 2 ? rest : important).push(e);
  }
  const creases = rest
    .map((e) => ({ e, angle: dihedralCosine(topology, e) }))
    .sort((a, b) => a.angle - b.angle);
  const room = Math.max(budget - important.length, 0);
  const sharp = creases.slice(0, Math.floor(room / 2)).map((c) => c.e);
  const sharpSet = new Set(sharp);
  const remaining = creases.map((c) => c.e).filter((e) => !sharpSet.has(e));
  const step = Math.max(Math.ceil(remaining.length / Math.max(room - sharp.length, 1)), 1);
  const sampled: number[] = [];
  for (let i = 0; i < remaining.length; i += step) sampled.push(remaining[i] as number);
  return [...important, ...sharp, ...sampled].slice(0, Math.max(budget, important.length)).sort((a, b) => a - b);
}

function faceNormal(topology: MeshTopology, face: number): [number, number, number] {
  const a = vertexAt(topology, topology.faces[face * 3] as number);
  const b = vertexAt(topology, topology.faces[face * 3 + 1] as number);
  const c = vertexAt(topology, topology.faces[face * 3 + 2] as number);
  const ux = b[0] - a[0];
  const uy = b[1] - a[1];
  const uz = b[2] - a[2];
  const vx = c[0] - a[0];
  const vy = c[1] - a[1];
  const vz = c[2] - a[2];
  const nx = uy * vz - uz * vy;
  const ny = uz * vx - ux * vz;
  const nz = ux * vy - uy * vx;
  const length = Math.hypot(nx, ny, nz) || 1;
  return [nx / length, ny / length, nz / length];
}

/** Cosine of the angle between the two faces on an edge; 1 is flat, -1 folds back. */
function dihedralCosine(topology: MeshTopology, edge: number): number {
  const f0 = topology.edgeFaces[edge * 2] as number;
  const f1 = topology.edgeFaces[edge * 2 + 1] as number;
  if (f0 < 0 || f1 < 0) return -1;
  const a = faceNormal(topology, f0);
  const b = faceNormal(topology, f1);
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

// ---------------------------------------------------------------------------------------
// World grid: snap increments and symmetry (T-234)
// ---------------------------------------------------------------------------------------

export const GRID_STEPS_MM: readonly number[] = [0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100];

export interface ModellingGrid {
  /** Snap increment in mm. */
  step_mm: number;
  /** Draw a heavier line every this many cells. */
  major_every: number;
  snap: boolean;
  /** Mirror edits across the plane through `symmetry_origin` perpendicular to each axis. */
  symmetry: Record<Axis, boolean>;
  /** Where the symmetry planes cross, in model mm. */
  symmetry_origin: [number, number, number];
}

export function defaultGrid(): ModellingGrid {
  return {
    step_mm: 5,
    major_every: 5,
    snap: false,
    symmetry: { x: false, y: false, z: false },
    symmetry_origin: [0, 0, 0],
  };
}

/** A grid step that gives readable cells for a model of the given largest dimension. */
export function suggestGridStep(largestMm: number): number {
  const target = Math.max(largestMm, 0.01) / 20;
  let best: number = GRID_STEPS_MM[0] as number;
  for (const step of GRID_STEPS_MM) if (Math.abs(Math.log(step / target)) < Math.abs(Math.log(best / target))) best = step;
  return best;
}

function snapScalar(value: number, step: number): number {
  return Math.round(value / step) * step;
}

/** Snap a point to the grid. A disabled grid or a non-positive step returns the point. */
export function snapPoint(
  point: readonly [number, number, number],
  grid: Pick<ModellingGrid, "step_mm" | "snap">,
): [number, number, number] {
  if (!grid.snap || !(grid.step_mm > 0)) return [point[0], point[1], point[2]];
  const clean = (v: number) => (Object.is(v, -0) ? 0 : Number(v.toFixed(6)));
  return [
    clean(snapScalar(point[0], grid.step_mm)),
    clean(snapScalar(point[1], grid.step_mm)),
    clean(snapScalar(point[2], grid.step_mm)),
  ];
}

/**
 * Every position an edit at `point` also applies to under the enabled symmetries — the
 * point itself first, then each distinct mirror (2 for one axis, 4 for two, 8 for three).
 */
export function symmetricPoints(
  point: readonly [number, number, number],
  grid: Pick<ModellingGrid, "symmetry" | "symmetry_origin">,
): [number, number, number][] {
  let points: [number, number, number][] = [[point[0], point[1], point[2]]];
  (["x", "y", "z"] as const).forEach((axis, i) => {
    if (!grid.symmetry[axis]) return;
    const centre = grid.symmetry_origin[i] as number;
    const mirrored = points.map((p): [number, number, number] => {
      const copy: [number, number, number] = [p[0], p[1], p[2]];
      copy[i] = 2 * centre - (p[i] as number);
      return copy;
    });
    const seen = new Set(points.map((p) => p.join(",")));
    points = points.concat(mirrored.filter((p) => !seen.has(p.join(","))));
  });
  return points;
}

// ---------------------------------------------------------------------------------------
// Symmetric selection
// ---------------------------------------------------------------------------------------

export interface TopologyLookup {
  tolerance: number;
  vertexByKey: Map<string, number>;
  edgeByPair: Map<number, number>;
  faceByTriple: Map<string, number>;
}

function positionKey(p: readonly number[], tolerance: number): string {
  const inverse = 1 / tolerance;
  return `${Math.round((p[0] as number) * inverse)},${Math.round((p[1] as number) * inverse)},${Math.round((p[2] as number) * inverse)}`;
}

/** Hash tables that answer "what is at this position / between these vertices" quickly. */
export function buildLookup(topology: MeshTopology, tolerance = 1e-3): TopologyLookup {
  const vertexByKey = new Map<string, number>();
  for (let v = 0; v < topology.report.vertices; v += 1) {
    vertexByKey.set(positionKey(vertexAt(topology, v), tolerance), v);
  }
  const edgeByPair = new Map<number, number>();
  for (let e = 0; e < topology.report.edges; e += 1) {
    edgeByPair.set((topology.edges[e * 2] as number) * topology.report.vertices + (topology.edges[e * 2 + 1] as number), e);
  }
  const faceByTriple = new Map<string, number>();
  for (let f = 0; f < topology.report.faces; f += 1) {
    const corners = [0, 1, 2].map((c) => topology.faces[f * 3 + c] as number).sort((a, b) => a - b);
    faceByTriple.set(corners.join(","), f);
  }
  return { tolerance, vertexByKey, edgeByPair, faceByTriple };
}

/**
 * The picked components plus their mirror images under the enabled symmetries. A component
 * whose mirror is not on the model (an asymmetric part) is kept alone rather than dropped.
 */
export function mirrorSelection(
  topology: MeshTopology,
  lookup: TopologyLookup,
  kind: ComponentKind,
  ids: Iterable<number>,
  grid: Pick<ModellingGrid, "symmetry" | "symmetry_origin">,
): number[] {
  const result = new Set<number>();
  const axes = (["x", "y", "z"] as const).flatMap((axis, i) => (grid.symmetry[axis] ? [i] : []));
  // Each mask picks a subset of the enabled planes. Every corner is mirrored by the same
  // mask, so a corner lying on a plane maps to itself instead of shifting the others' copy.
  const mirrorVertex = (id: number, mask: number): number | undefined => {
    const point = vertexAt(topology, id);
    axes.forEach((axis, bit) => {
      if (mask & (1 << bit)) point[axis] = 2 * (grid.symmetry_origin[axis] as number) - point[axis];
    });
    return lookup.vertexByKey.get(positionKey(point, lookup.tolerance));
  };
  for (const id of ids) {
    result.add(id);
    const corners = verticesOf(topology, kind, [id]);
    for (let mask = 1; mask < 1 << axes.length; mask += 1) {
      const mapped = corners.map((corner) => mirrorVertex(corner, mask));
      if (mapped.some((v) => v === undefined)) continue;
      const found = mapped as number[];
      if (kind === "vertex") result.add(found[0] as number);
      else if (kind === "edge") {
        const lo = Math.min(found[0] as number, found[1] as number);
        const hi = Math.max(found[0] as number, found[1] as number);
        const edge = lookup.edgeByPair.get(lo * topology.report.vertices + hi);
        if (edge !== undefined) result.add(edge);
      } else {
        const face = lookup.faceByTriple.get([...found].sort((a, b) => a - b).join(","));
        if (face !== undefined) result.add(face);
      }
    }
  }
  return [...result].sort((a, b) => a - b);
}
