export interface DimensionedDrawingTrace {
  width_mm: number;
  height_mm: number;
  thickness_mm: number;
  corner_radius_mm: number;
  holes: { x_mm: number; y_mm: number; diameter_mm: number }[];
}

function numberOf(value: string): number {
  return Number(value.replace(",", "."));
}

export function parseDimensionedDrawingHoles(
  value: string,
): DimensionedDrawingTrace["holes"] | null {
  if (!value.trim()) return [];
  const holes = value
    .split(/\n+/)
    .filter((line) => line.trim())
    .map((line) => line.replace(/[Ø⌀]/gi, "").split(/[;,\s]+/).filter(Boolean).map(numberOf));
  if (
    holes.length > 32
    || holes.some((hole) => hole.length !== 3 || hole.some((part) => !Number.isFinite(part)))
  ) return null;
  return holes.map(([x, y, diameter]) => ({ x_mm: x!, y_mm: y!, diameter_mm: diameter! }));
}

export function dimensionedDrawingNumber(value: string): number {
  return numberOf(value);
}
