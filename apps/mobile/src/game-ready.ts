export type LodRatioInput =
  | { ok: true; ratios: [number, number] }
  | { ok: false; reason: "range" | "order" };

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
