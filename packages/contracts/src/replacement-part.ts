/** Honest client-side boundary for reference 71 (camera → replacement part). */

export const REPLACEMENT_DIMENSIONS = ["length", "width", "height", "hole_diameter"] as const;
export type ReplacementDimension = (typeof REPLACEMENT_DIMENSIONS)[number];

export function replacementDimensionLabel(
  dimension: ReplacementDimension,
  language: "ru" | "en",
): string {
  const labels = {
    length: { ru: "Длина", en: "Length" },
    width: { ru: "Ширина", en: "Width" },
    height: { ru: "Высота", en: "Height" },
    hole_diameter: { ru: "Ø отверстия", en: "Hole Ø" },
  } as const;
  return labels[dimension][language];
}
export function parseReplacementKnownMm(value: string): number | null {
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 && parsed <= 10_000 ? parsed : null;
}
