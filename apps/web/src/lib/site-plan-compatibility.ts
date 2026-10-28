import type { Project, SitePlanCompatibility } from "@physical-ai/contracts";

const EPSILON_MM = 1e-6;
const TERRAIN_SIZE_TOLERANCE_MM = 1;

function finitePair(value: number[] | null): value is [number, number] {
  return Array.isArray(value)
    && value.length === 2
    && value.every((item) => Number.isFinite(item) && item > 0);
}

function finiteNonnegativePair(value: number[] | null): value is [number, number] {
  return Array.isArray(value)
    && value.length === 2
    && value.every((item) => Number.isFinite(item) && item >= 0);
}

function close(left: number, right: number, tolerance = EPSILON_MM): boolean {
  return Math.abs(left - right) <= tolerance;
}

/** Bind a pre-purchase site report to the selected head and recheck its derived facts. */
export function verifiedSitePlanCompatibility(
  report: SitePlanCompatibility,
  project: Project | undefined,
): SitePlanCompatibility | null {
  if (
    !project
    || report.project_id !== project.id
    || report.project_name !== project.name
    || report.version_id !== project.head_version_id
  ) return null;

  const terrainAbsent = report.terrain_rotation_deg === null
    && report.terrain_corner_delta_mm === null
    && report.terrain_max_delta_mm === null;

  if (report.status === "unsupported") {
    const validRequired = report.required_size_mm === null || finitePair(report.required_size_mm);
    return typeof report.reason === "string"
      && report.reason.length > 0
      && validRequired
      && report.available_size_mm === null
      && report.spare_size_mm === null
      && terrainAbsent
      ? report
      : null;
  }

  if (
    report.reason !== null
    || !finitePair(report.required_size_mm)
    || !finitePair(report.available_size_mm)
  ) return null;

  const [requiredLength, requiredWidth] = report.required_size_mm;
  const [availableLength, availableWidth] = report.available_size_mm;
  const directSpare: [number, number] = [
    availableLength - requiredLength,
    availableWidth - requiredWidth,
  ];
  const rotatedSpare: [number, number] = [
    availableLength - requiredWidth,
    availableWidth - requiredLength,
  ];
  const expectedStatus = Math.min(...directSpare) >= 0
    ? "compatible"
    : Math.min(...rotatedSpare) >= 0
      ? "rotated"
      : "incompatible";
  if (report.status !== expectedStatus) return null;

  const expectedSpare = expectedStatus === "compatible"
    ? directSpare
    : expectedStatus === "rotated"
      ? rotatedSpare
      : null;
  if (expectedSpare === null) {
    if (report.spare_size_mm !== null) return null;
  } else if (
    !finiteNonnegativePair(report.spare_size_mm)
    || !close(report.spare_size_mm[0], expectedSpare[0])
    || !close(report.spare_size_mm[1], expectedSpare[1])
  ) return null;

  const sameEnvelope = close(requiredLength, availableLength, TERRAIN_SIZE_TOLERANCE_MM)
    && close(requiredWidth, availableWidth, TERRAIN_SIZE_TOLERANCE_MM);
  const swappedEnvelope = !sameEnvelope
    && close(requiredWidth, availableLength, TERRAIN_SIZE_TOLERANCE_MM)
    && close(requiredLength, availableWidth, TERRAIN_SIZE_TOLERANCE_MM);
  if (!sameEnvelope && !swappedEnvelope) return terrainAbsent ? report : null;

  const deltas = report.terrain_corner_delta_mm;
  const rotation = report.terrain_rotation_deg;
  if (
    !Array.isArray(deltas)
    || deltas.length !== 4
    || !deltas.every(Number.isFinite)
    || !close(deltas[0], 0)
    || report.terrain_max_delta_mm === null
    || !Number.isFinite(report.terrain_max_delta_mm)
    || report.terrain_max_delta_mm < 0
    || !close(report.terrain_max_delta_mm, Math.max(...deltas.map(Math.abs)))
  ) return null;
  const allowedRotations: readonly number[] = sameEnvelope ? [0, 180] : [90, 270];
  return rotation !== null && allowedRotations.includes(rotation) ? report : null;
}
