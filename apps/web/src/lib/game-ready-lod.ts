/** Reference 83/84/86: web parity for mobile's game-ready LOD0-LOD2 preparation/preview, its
 * per-object UV atlas evidence and its per-object convex/box collider (UCX) evidence. Mechanism
 * animation (87) and the full multi-feature export (88) are separate scenarios and are not
 * validated here. */

export type LodShareInput =
  | { ok: true; ratios: [number, number] }
  | { ok: false; reason: "range" | "order" };

export interface VerifiedGameLod {
  name: string;
  triangles: number;
  vertices: number;
  max_deviation_mm: number;
}

/** Convert the two visible LOD1/LOD2 percentages into the worker's descending LOD0 shares. */
export function parseLodShares(lod1Text: string, lod2Text: string): LodShareInput {
  const lod1 = Number(lod1Text.trim().replace(",", "."));
  const lod2 = Number(lod2Text.trim().replace(",", "."));
  if (!Number.isFinite(lod1) || !Number.isFinite(lod2) || lod1 < 1 || lod1 > 99 || lod2 < 1 || lod2 > 99) {
    return { ok: false, reason: "range" };
  }
  if (lod2 >= lod1) return { ok: false, reason: "order" };
  return { ok: true, ratios: [lod1 / 100, lod2 / 100] };
}

/** The preview selector is trustworthy only when the worker report describes exactly the
 * requested, ordered GLB nodes and every displayed measurement is finite. A preserved small
 * mesh may have equal triangle counts across levels, so density is only non-increasing. */
export function gameReadyLodsMatchRequest(
  value: unknown,
  modelName: string,
  maxTriangles: number,
  requestedLighterLevels: number,
): value is VerifiedGameLod[] {
  if (
    !Array.isArray(value)
    || value.length !== requestedLighterLevels + 1
    || !Number.isInteger(maxTriangles)
    || maxTriangles <= 0
    || !Number.isInteger(requestedLighterLevels)
    || requestedLighterLevels < 0
  ) return false;

  let previousTriangles = Number.POSITIVE_INFINITY;
  return value.every((candidate, index) => {
    if (!candidate || typeof candidate !== "object") return false;
    const lod = candidate as Partial<VerifiedGameLod>;
    const valid = (
      lod.name === `${modelName}_LOD${index}`
      && Number.isInteger(lod.triangles)
      && (lod.triangles ?? 0) > 0
      && Number.isInteger(lod.vertices)
      && (lod.vertices ?? 0) > 0
      && Number.isFinite(lod.max_deviation_mm)
      && (lod.max_deviation_mm ?? -1) >= 0
      && (index !== 0 || lod.triangles! <= maxTriangles)
      && lod.triangles! <= previousTriangles
    );
    if (valid) previousTriangles = lod.triangles!;
    return valid;
  });
}

export interface VerifiedUvAtlas {
  lod: string;
  triangleAreaPct: number;
  degenerateTriangles: number;
  outOfBoundsVertices: number;
}

/** UV evidence must cover the exact verified LOD set, one atlas per LOD matched by name and
 * index. The summed triangle area is a measured percentage, not an overlap-aware packing or
 * distortion score, so it is only required to be finite and positive; degenerate/out-of-bounds
 * counts are non-negative integers. Returns null (fail closed) on any mismatch, or an empty
 * array when UV was not requested. */
export function gameReadyUvAtlasesMatchLods(
  reportValue: unknown,
  lods: VerifiedGameLod[],
  uvRequested: boolean,
): VerifiedUvAtlas[] | null {
  if (!reportValue || typeof reportValue !== "object") return null;
  const report = reportValue as { uv?: unknown; uv_atlases?: unknown };
  if (report.uv !== uvRequested) return null;
  if (!uvRequested) return [];
  if (!Array.isArray(report.uv_atlases) || report.uv_atlases.length !== lods.length) return null;

  const verified: VerifiedUvAtlas[] = [];
  for (let index = 0; index < lods.length; index += 1) {
    const candidate = report.uv_atlases[index];
    if (!candidate || typeof candidate !== "object") return null;
    const atlas = candidate as Partial<{
      lod: unknown;
      triangle_area_pct: unknown;
      degenerate_triangles: unknown;
      out_of_bounds_vertices: unknown;
    }>;
    const lod = lods[index]!;
    if (
      atlas.lod !== lod.name
      || !Number.isFinite(atlas.triangle_area_pct)
      || (atlas.triangle_area_pct as number) <= 0
      || !Number.isInteger(atlas.degenerate_triangles)
      || (atlas.degenerate_triangles as number) < 0
      || !Number.isInteger(atlas.out_of_bounds_vertices)
      || (atlas.out_of_bounds_vertices as number) < 0
    ) return null;
    verified.push({
      lod: atlas.lod as string,
      triangleAreaPct: atlas.triangle_area_pct as number,
      degenerateTriangles: atlas.degenerate_triangles as number,
      outOfBoundsVertices: atlas.out_of_bounds_vertices as number,
    });
  }
  return verified;
}

/** A single-object export is trustworthy only when the envelope proves the requested pivot
 * and exact file size, and LOD0 is itself drawn from the same measured source triangle count. */
export function gameReadyEnvelopeMatchesRequest(
  reportValue: unknown,
  byteSize: unknown,
  requestedPivot: "base" | "centre" | "keep",
): boolean {
  if (!reportValue || typeof reportValue !== "object") return false;
  const report = reportValue as {
    ok?: unknown;
    pivot?: unknown;
    file_bytes?: unknown;
    triangles_in?: unknown;
    lods?: unknown;
  };
  if (
    report.ok !== true
    || report.pivot !== requestedPivot
    || !Number.isInteger(byteSize)
    || (byteSize as number) <= 0
    || report.file_bytes !== byteSize
    || !Number.isInteger(report.triangles_in)
    || (report.triangles_in as number) <= 0
    || !Array.isArray(report.lods)
  ) return false;
  const lod0 = report.lods[0] as { triangles?: unknown } | undefined;
  return Number.isInteger(lod0?.triangles) && (lod0?.triangles as number) <= (report.triangles_in as number);
}

export interface VerifiedGameCollider {
  /** The worker-reported UCX node name, e.g. "UCX_SovaModel_00". */
  name: string;
  kind: "convex" | "box";
  triangles: number;
  triangleLimit: number;
  isConvex: boolean;
  isWatertight: boolean;
  volumeRatioPct: number | null;
  floorOffsetMm: number;
}

export type VerifiedGameColliderResult =
  | { ok: true; collider: VerifiedGameCollider | null }
  | { ok: false };

/** A collider selector may expose only the exact requested UCX node with bounded, measured,
 * convex and watertight geometry; a "none" request must carry no collider at all. Fails closed
 * (ok: false) on any mismatch or substitution instead of returning a null that could be mistaken
 * for the valid "no collider requested" case. */
export function gameReadyColliderMatchesRequest(
  reportValue: unknown,
  modelName: string,
  requested: "convex" | "box" | "none",
): VerifiedGameColliderResult {
  if (!reportValue || typeof reportValue !== "object") return { ok: false };
  const collider = (reportValue as { collider?: unknown }).collider;
  if (requested === "none") {
    return collider == null ? { ok: true, collider: null } : { ok: false };
  }
  if (!collider || typeof collider !== "object") return { ok: false };
  const evidence = collider as Partial<{
    name: unknown;
    kind: unknown;
    triangles: unknown;
    triangle_limit: unknown;
    is_convex: unknown;
    is_watertight: unknown;
    volume_ratio_pct: unknown;
    floor_offset_mm: unknown;
  }>;
  const valid = (
    evidence.name === `UCX_${modelName}_00`
    && evidence.kind === requested
    && Number.isInteger(evidence.triangles)
    && (evidence.triangles as number) > 0
    && Number.isInteger(evidence.triangle_limit)
    && (evidence.triangle_limit as number) > 0
    && (evidence.triangles as number) <= (evidence.triangle_limit as number)
    && evidence.is_convex === true
    && evidence.is_watertight === true
    && (
      evidence.volume_ratio_pct === null
      || (Number.isFinite(evidence.volume_ratio_pct) && (evidence.volume_ratio_pct as number) > 0)
    )
    && Number.isFinite(evidence.floor_offset_mm)
  );
  if (!valid) return { ok: false };
  return {
    ok: true,
    collider: {
      name: evidence.name as string,
      kind: evidence.kind as "convex" | "box",
      triangles: evidence.triangles as number,
      triangleLimit: evidence.triangle_limit as number,
      isConvex: evidence.is_convex as boolean,
      isWatertight: evidence.is_watertight as boolean,
      volumeRatioPct: evidence.volume_ratio_pct as number | null,
      floorOffsetMm: evidence.floor_offset_mm as number,
    },
  };
}

export interface VerifiedGameReadyObject {
  nodeId: string;
  /** Original scene-tree label. */
  name: string;
  /** Worker-sanitized identifier used by the LOD nodes in the GLB. */
  engineName: string;
  trianglesIn: number;
  lods: VerifiedGameLod[];
  uvAtlases: VerifiedUvAtlas[];
  collider: VerifiedGameCollider | null;
}

/** A scene's aggregate LOD report is trustworthy only when every visible object's own LOD, UV
 * atlas and collider evidence independently passes the same per-object checks a single-object
 * export must pass, every object id in the report is unique, and the summed source triangles
 * match the reported total — so one object's evidence cannot be silently dropped or substituted. */
export function gameReadySceneReportMatchesRequest(
  reportValue: unknown,
  byteSize: unknown,
  requestedPivot: "base" | "centre" | "keep",
  maxTriangles: number,
  requestedLighterLevels: number,
  uvRequested: boolean,
  colliderRequested: "convex" | "box" | "none",
): VerifiedGameReadyObject[] | null {
  if (!reportValue || typeof reportValue !== "object") return null;
  const report = reportValue as {
    ok?: unknown;
    pivot?: unknown;
    file_bytes?: unknown;
    objects?: unknown;
    triangles_in?: unknown;
    per_object?: unknown;
  };
  if (
    report.ok !== true
    || report.pivot !== requestedPivot
    || !Number.isInteger(byteSize)
    || (byteSize as number) <= 0
    || report.file_bytes !== byteSize
    || !Number.isInteger(report.objects)
    || (report.objects as number) < 1
    || !Array.isArray(report.per_object)
    || report.per_object.length !== report.objects
  ) return null;

  const seen = new Set<string>();
  const verified: VerifiedGameReadyObject[] = [];
  let triangleSum = 0;
  for (const raw of report.per_object) {
    if (!raw || typeof raw !== "object") return null;
    const entry = raw as { node_id?: unknown; source_name?: unknown; name?: unknown; report?: unknown };
    if (typeof entry.node_id !== "string" || seen.has(entry.node_id)) return null;
    if (typeof entry.source_name !== "string" || entry.source_name.length === 0) return null;
    if (typeof entry.name !== "string" || entry.name.length === 0) return null;
    seen.add(entry.node_id);
    const objectReport = entry.report as { ok?: unknown; pivot?: unknown; lods?: unknown; triangles_in?: unknown } | undefined;
    if (objectReport?.ok !== true || objectReport.pivot !== "keep") return null;
    if (!gameReadyLodsMatchRequest(objectReport?.lods, entry.name, maxTriangles, requestedLighterLevels)) {
      return null;
    }
    if (!Number.isInteger(objectReport!.triangles_in) || (objectReport!.triangles_in as number) <= 0) {
      return null;
    }
    const objectLods = objectReport!.lods as VerifiedGameLod[];
    const uvAtlases = gameReadyUvAtlasesMatchLods(entry.report, objectLods, uvRequested);
    if (!uvAtlases) return null;
    const colliderResult = gameReadyColliderMatchesRequest(entry.report, entry.name, colliderRequested);
    if (!colliderResult.ok) return null;
    triangleSum += objectReport!.triangles_in as number;
    verified.push({
      nodeId: entry.node_id,
      name: entry.source_name,
      engineName: entry.name,
      trianglesIn: objectReport!.triangles_in as number,
      lods: objectLods,
      uvAtlases,
      collider: colliderResult.collider,
    });
  }
  if (triangleSum !== report.triangles_in) return null;
  return verified;
}
