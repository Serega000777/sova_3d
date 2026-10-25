import type { RegionSelection } from "@physical-ai/contracts";

export type EngineeringRiskBox = {
  key: string;
  min: [number, number, number];
  max: [number, number, number];
};

/** A renderable model-space box only when every server coordinate is finite and ordered. */
export function engineeringRiskBox(
  selection: RegionSelection | null | undefined,
): EngineeringRiskBox | null {
  if (!selection || selection.region.kind !== "box") return null;
  const min = selection.region.min_mm;
  const max = selection.region.max_mm;
  if (
    min.length !== 3
    || max.length !== 3
    || min.some((value) => !Number.isFinite(value))
    || max.some((value) => !Number.isFinite(value))
    || max.some((value, index) => value <= min[index]!)
  ) return null;
  return {
    key: "engineering-load-risk",
    min: [min[0]!, min[1]!, min[2]!],
    max: [max[0]!, max[1]!, max[2]!],
  };
}
