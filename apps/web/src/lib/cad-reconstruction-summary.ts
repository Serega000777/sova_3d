export type CadReconstructionSummary = {
  sourceVersionId: string;
  dimensionsMm: [number, number, number] | null;
  faceCount: number;
  watertight: boolean;
  planeCount: number;
  holeCount: number;
  patternCount: number;
  threadCount: number;
  fidelity: "prismatic" | "stepped" | "freeform";
  levels: number;
  unexplainedLevels: number;
  toleranceMm: number;
  meanMm: number;
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

function nonNegativeInteger(value: unknown): number | null {
  const parsed = finite(value);
  return parsed !== null && Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

function reconstructedDimensions(root: Record<string, unknown>): [number, number, number] | null {
  const expectedOutputs = Array.isArray(root.expected_outputs) ? root.expected_outputs : [];
  const bodies = Array.isArray(root.bodies) ? root.bodies : [];
  if (expectedOutputs.length !== 1 || typeof expectedOutputs[0] !== "string") return null;
  const matches = bodies
    .map(record)
    .filter((body): body is Record<string, unknown> => body?.name === expectedOutputs[0]);
  if (matches.length !== 1 || matches[0].valid !== true) return null;
  const size = record(matches[0].bbox_mm)?.size;
  if (!Array.isArray(size) || size.length !== 3) return null;
  const parsed = size.map(finite);
  if (parsed.some((value) => value === null || value <= 0)) return null;
  return parsed as [number, number, number];
}

/**
 * Restore the durable Mesh -> CAD report from an immutable child version.
 * Every required measured field fails closed; dimensions are optional because legacy
 * kernel records may not identify one unambiguous valid output body.
 */
export function cadReconstructionSummaryForVersion(version: {
  parent_version_id: string | null;
  provenance: unknown;
}): CadReconstructionSummary | null {
  const root = record(version.provenance);
  if (!root || root.operation !== "reverse_engineer") return null;
  const sourceVersionId = root.source_version_id;
  if (typeof sourceVersionId !== "string" || version.parent_version_id !== sourceVersionId) return null;

  const features = record(root.feature_report);
  const deviation = record(root.deviation);
  const reconstruction = record(features?.reconstruction);
  const fidelity = reconstruction?.fidelity;
  const faceCount = nonNegativeInteger(features?.faces);
  const levels = nonNegativeInteger(reconstruction?.levels);
  const unexplainedLevels = nonNegativeInteger(reconstruction?.unexplained_levels);
  const toleranceMm = finite(deviation?.tolerance_mm);
  const meanMm = finite(deviation?.mean_mm);
  const p95Mm = finite(deviation?.p95_mm);
  const maxMm = finite(deviation?.max_mm);
  const withinTolerance = finite(deviation?.within_tolerance);
  const samples = nonNegativeInteger(deviation?.samples);
  if (
    !features
    || features.ok !== true
    || typeof features.watertight !== "boolean"
    || !["prismatic", "stepped", "freeform"].includes(String(fidelity))
    || faceCount === null
    || levels === null
    || unexplainedLevels === null
    || toleranceMm === null
    || toleranceMm <= 0
    || meanMm === null
    || meanMm < 0
    || p95Mm === null
    || p95Mm < 0
    || maxMm === null
    || maxMm < 0
    || withinTolerance === null
    || withinTolerance < 0
    || withinTolerance > 1
    || samples === null
    || samples <= 0
  ) return null;

  const cylinders = Array.isArray(features.cylinders) ? features.cylinders : [];
  return {
    sourceVersionId,
    dimensionsMm: reconstructedDimensions(root),
    faceCount,
    watertight: features.watertight,
    planeCount: Array.isArray(features.planes) ? features.planes.length : 0,
    holeCount: cylinders.filter((value) => record(value)?.kind === "hole").length,
    patternCount: Array.isArray(features.patterns) ? features.patterns.length : 0,
    threadCount: Array.isArray(features.threads) ? features.threads.length : 0,
    fidelity: fidelity as CadReconstructionSummary["fidelity"],
    levels,
    unexplainedLevels,
    toleranceMm,
    meanMm,
    p95Mm,
    maxMm,
    withinTolerance,
    samples,
    warnings: Array.isArray(features.warnings)
      ? features.warnings.filter((value): value is string => typeof value === "string")
      : [],
  };
}
