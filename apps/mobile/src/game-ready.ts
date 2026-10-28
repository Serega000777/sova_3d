export type LodRatioInput =
  | { ok: true; ratios: [number, number] }
  | { ok: false; reason: "range" | "order" };

export interface VerifiedGameLod {
  name: string;
  triangles: number;
  vertices: number;
  max_deviation_mm: number;
}

interface GameUvAtlas {
  lod: string;
  triangle_area_pct: number;
  degenerate_triangles: number;
  out_of_bounds_vertices: number;
}

interface GameColliderEvidence {
  name: string;
  kind: "convex" | "box";
  triangles: number;
  triangle_limit: number;
  is_convex: boolean;
  is_watertight: boolean;
  volume_ratio_pct: number | null;
  floor_offset_mm: number;
}

/** Convert the two visible percentages into the worker's descending LOD0 shares. */
export function parseLodRatios(lod1Text: string, lod2Text: string): LodRatioInput {
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
 * mesh may have equal triangle counts across levels, so density is non-increasing. */
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

/** UV evidence must cover the exact verified LOD set. The area is a measured triangle sum,
 * not an overlap-aware packing score, so it is only required to be finite and positive. */
export function gameReadyUvReportMatchesLods(
  reportValue: unknown,
  lodValue: unknown,
  uvRequested: boolean,
): boolean {
  if (!reportValue || typeof reportValue !== "object") return false;
  const report = reportValue as { uv?: unknown; uv_atlases?: unknown };
  if (report.uv !== uvRequested) return false;
  if (!uvRequested) return true;
  if (!Array.isArray(lodValue) || !Array.isArray(report.uv_atlases)) return false;
  if (report.uv_atlases.length !== lodValue.length) return false;

  return report.uv_atlases.every((candidate, index) => {
    if (!candidate || typeof candidate !== "object") return false;
    const atlas = candidate as Partial<GameUvAtlas>;
    const lod = lodValue[index] as Partial<VerifiedGameLod> | undefined;
    return (
      typeof lod?.name === "string"
      && atlas.lod === lod.name
      && Number.isFinite(atlas.triangle_area_pct)
      && (atlas.triangle_area_pct ?? 0) > 0
      && Number.isInteger(atlas.degenerate_triangles)
      && (atlas.degenerate_triangles ?? -1) >= 0
      && Number.isInteger(atlas.out_of_bounds_vertices)
      && (atlas.out_of_bounds_vertices ?? -1) >= 0
    );
  });
}

/** A collider selector may expose only the exact requested UCX node with bounded, measured
 * geometry. This proves one exported shape, not contacts, mass, gravity or dynamics. */
export function gameReadyColliderMatchesRequest(
  reportValue: unknown,
  modelName: string,
  requested: "convex" | "box" | "none",
): boolean {
  if (!reportValue || typeof reportValue !== "object") return false;
  const collider = (reportValue as { collider?: unknown }).collider;
  if (requested === "none") return collider == null;
  if (!collider || typeof collider !== "object") return false;
  const evidence = collider as Partial<GameColliderEvidence>;
  return (
    evidence.name === `UCX_${modelName}_00`
    && evidence.kind === requested
    && Number.isInteger(evidence.triangles)
    && (evidence.triangles ?? 0) > 0
    && Number.isInteger(evidence.triangle_limit)
    && (evidence.triangle_limit ?? 0) > 0
    && evidence.triangles! <= evidence.triangle_limit!
    && evidence.is_convex === true
    && evidence.is_watertight === true
    && (
      evidence.volume_ratio_pct === null
      || (Number.isFinite(evidence.volume_ratio_pct) && evidence.volume_ratio_pct! > 0)
    )
    && Number.isFinite(evidence.floor_offset_mm)
  );
}

/** The independently checked sections still belong to one trustworthy game asset only when
 * the worker envelope proves the requested pivot, metric engine bounds and exact file size. */
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
    size_m?: unknown;
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
    || !Array.isArray(report.size_m)
    || report.size_m.length !== 3
    || report.size_m.some((value) => typeof value !== "number" || !Number.isFinite(value) || value <= 0)
    || !Array.isArray(report.lods)
  ) return false;
  const lod0 = report.lods[0] as { triangles?: unknown } | undefined;
  return Number.isInteger(lod0?.triangles) && (lod0?.triangles as number) <= (report.triangles_in as number);
}
