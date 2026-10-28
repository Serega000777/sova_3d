export type DimensionAxis = "x" | "y" | "z";
export type DimensionDraft = Record<DimensionAxis, string>;
export type DimensionSize = Record<DimensionAxis, number>;

export function parseDimensionValue(value: string): number | null {
  const parsed = Number(value.trim().replace(",", "."));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** Update one field, optionally deriving the other axes from the measured source envelope. */
export function updateDimensionDraft(
  current: Record<string, string>,
  axis: DimensionAxis,
  value: string,
  source: DimensionSize,
  linked: boolean,
): Record<string, string> {
  if (!linked) return { ...current, [axis]: value };
  const next = parseDimensionValue(value);
  if (next === null || !Number.isFinite(source[axis]) || source[axis] <= 0) {
    return { ...current, [axis]: value };
  }
  const ratio = next / source[axis];
  return Object.fromEntries(
    (["x", "y", "z"] as const).map((candidate) => [
      candidate,
      candidate === axis
        ? value
        : Number((source[candidate] * ratio).toFixed(2)).toString(),
    ]),
  );
}
