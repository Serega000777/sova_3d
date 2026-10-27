export type CadRestorationBoundary = "x_min" | "x_max" | "y_min" | "y_max" | "z_min" | "z_max";

export type CadReconstructionSummary = {
  sourceVersionId: string;
  dimensionsMm: [number, number, number] | null;
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
  restoration: {
    boundary: CadRestorationBoundary;
    requiresPhysicalValidation: true;
  } | null;
  reinforcement: {
    percent: number;
    certified: false;
    requiresPhysicalValidation: true;
  } | null;
};

const RESTORATION_BOUNDARIES: CadRestorationBoundary[] = [
  "x_min", "x_max", "y_min", "y_max", "z_min", "z_max",
];

export function cadRestorationBoundaryLabel(boundary: CadRestorationBoundary): string {
  return `${boundary[0].toUpperCase()}${boundary.endsWith("_min") ? "−" : "+"}`;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function reconstructedDimensions(root: Record<string, unknown>): [number, number, number] | null {
  const expectedOutputs = Array.isArray(root.expected_outputs) ? root.expected_outputs : [];
  const bodies = Array.isArray(root.bodies) ? root.bodies : [];
  if (expectedOutputs.length !== 1 || typeof expectedOutputs[0] !== "string") return null;
  const matches = bodies
    .map(record)
    .filter((body): body is Record<string, unknown> => body?.name === expectedOutputs[0]);
  if (matches.length !== 1) return null;
  const size = record(matches[0]?.bbox_mm)?.size;
  if (!Array.isArray(size) || size.length !== 3) return null;
  const parsed = size.map(finite);
  if (parsed.some((value) => value === null || value <= 0)) return null;
  return parsed as [number, number, number];
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
  const restorationValue = record(root.restoration);
  const restorationBoundary = restorationValue?.boundary;
  const restoration = (
    restorationValue?.mode === "mirrored_missing_half"
    && typeof restorationBoundary === "string"
    && RESTORATION_BOUNDARIES.includes(restorationBoundary as CadRestorationBoundary)
    && restorationValue.requires_physical_validation === true
  ) ? {
      boundary: restorationBoundary as CadRestorationBoundary,
      requiresPhysicalValidation: true as const,
    } : null;
  const reinforcementValue = record(root.reinforcement);
  const reinforcementPercent = finite(reinforcementValue?.percent);
  const reinforcement = (
    reinforcementValue?.mode === "thickness_percent"
    && reinforcementValue.datum === "minimum_z"
    && reinforcementPercent !== null
    && reinforcementPercent > 0
    && reinforcementPercent <= 50
    && reinforcementValue.certified === false
    && reinforcementValue.requires_physical_validation === true
  ) ? {
      percent: reinforcementPercent,
      certified: false as const,
      requiresPhysicalValidation: true as const,
    } : null;
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
    dimensionsMm: reconstructedDimensions(root),
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
    restoration,
    reinforcement,
  };
}
