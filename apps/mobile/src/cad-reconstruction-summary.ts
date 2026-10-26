export type CadReconstructionSummary = {
  sourceVersionId: string;
  planeCount: number;
  holeCount: number;
  patternCount: number;
  threadCount: number;
  fidelity: "prismatic" | "stepped" | "freeform";
  levels: number;
  unexplainedLevels: number;
  toleranceMm: number;
  p95Mm: number;
  maxMm: number;
  withinTolerance: number;
  samples: number;
  warnings: string[];
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function cadReconstructionSummaryFromProvenance(
  provenance: unknown,
): CadReconstructionSummary | null {
  const root = record(provenance);
  if (!root || root.operation !== "reverse_engineer") return null;
  const features = record(root.feature_report);
  const deviation = record(root.deviation);
  const reconstruction = record(features?.reconstruction);
  const sourceVersionId = root.source_version_id;
  const fidelity = reconstruction?.fidelity;
  const levels = finite(reconstruction?.levels);
  const unexplainedLevels = finite(reconstruction?.unexplained_levels);
  const toleranceMm = finite(deviation?.tolerance_mm);
  const p95Mm = finite(deviation?.p95_mm);
  const maxMm = finite(deviation?.max_mm);
  const withinTolerance = finite(deviation?.within_tolerance);
  const samples = finite(deviation?.samples);
  if (
    typeof sourceVersionId !== "string"
    || !["prismatic", "stepped", "freeform"].includes(String(fidelity))
    || levels === null
    || unexplainedLevels === null
    || toleranceMm === null
    || p95Mm === null
    || maxMm === null
    || withinTolerance === null
    || samples === null
  ) return null;

  const cylinders = Array.isArray(features?.cylinders) ? features.cylinders : [];
  return {
    sourceVersionId,
    planeCount: Array.isArray(features?.planes) ? features.planes.length : 0,
    holeCount: cylinders.filter((value) => record(value)?.kind === "hole").length,
    patternCount: Array.isArray(features?.patterns) ? features.patterns.length : 0,
    threadCount: Array.isArray(features?.threads) ? features.threads.length : 0,
    fidelity: fidelity as CadReconstructionSummary["fidelity"],
    levels,
    unexplainedLevels,
    toleranceMm,
    p95Mm,
    maxMm,
    withinTolerance,
    samples,
    warnings: Array.isArray(features?.warnings)
      ? features.warnings.filter((value): value is string => typeof value === "string")
      : [],
  };
}
