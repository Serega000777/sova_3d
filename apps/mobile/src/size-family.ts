import { MAX_EXACT_DETAIL_MM } from "@physical-ai/contracts";

export type SizeFamilyLabel = "S" | "M" | "L";

export type SizeFamilyDraft = Record<
  SizeFamilyLabel,
  { width: string; depth: string; height: string }
>;

export type SizeFamilyPreset = {
  label: SizeFamilyLabel;
  widthMm: number;
  depthMm: number;
  heightMm: number;
};

const LABELS: readonly SizeFamilyLabel[] = ["S", "M", "L"];
const WIDTH_FACTORS: Record<SizeFamilyLabel, number> = { S: 0.75, M: 1, L: 1.25 };

function formatMillimetres(value: number): string {
  return (Math.round(value * 1_000) / 1_000).toString();
}

/** Start with the familiar width-only family while leaving every exact dimension editable. */
export function defaultSizeFamilyDraft(bounds: {
  x: number;
  y: number;
  z: number;
}): SizeFamilyDraft {
  return Object.fromEntries(
    LABELS.map((label) => [
      label,
      {
        width: formatMillimetres(bounds.x * WIDTH_FACTORS[label]),
        depth: formatMillimetres(bounds.y),
        height: formatMillimetres(bounds.z),
      },
    ]),
  ) as SizeFamilyDraft;
}

function parseDimension(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed <= 0 || parsed > MAX_EXACT_DETAIL_MM) return null;
  return Math.round(parsed * 1_000) / 1_000;
}

/** Parse the complete table atomically so no partial family can reach the preview API. */
export function parseSizeFamilyDraft(draft: SizeFamilyDraft): SizeFamilyPreset[] | null {
  const result: SizeFamilyPreset[] = [];
  for (const label of LABELS) {
    const row = draft[label];
    const widthMm = parseDimension(row.width);
    const depthMm = parseDimension(row.depth);
    const heightMm = parseDimension(row.height);
    if (widthMm === null || depthMm === null || heightMm === null) return null;
    result.push({ label, widthMm, depthMm, heightMm });
  }
  return result;
}

/** A family label is trustworthy only when the kernel's measured output matches the exact
 * row that requested it. The small tolerance covers serialization/meshing precision, not a
 * different nominal size. */
export function sizeFamilyOutputMatches(
  measured: readonly number[],
  preset: SizeFamilyPreset,
  toleranceMm = 0.01,
): measured is readonly [number, number, number] {
  if (
    measured.length !== 3
    || !Number.isFinite(toleranceMm)
    || toleranceMm < 0
    || !measured.every((value) => Number.isFinite(value) && value > 0)
  ) return false;
  const expected = [preset.widthMm, preset.depthMm, preset.heightMm];
  return measured.every((value, index) => Math.abs(value - expected[index]!) <= toleranceMm);
}
