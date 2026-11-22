import type { RegionSelection, Version } from "./client.js";

export interface RestorableLocalEditDraft {
  version: Version;
  sourceVersionId: string;
  command: string;
  region: RegionSelection;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function boundedNumber(value: unknown, low: number, high: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= low && value <= high;
}

function point(value: unknown, length: number): number[] | null {
  if (!Array.isArray(value) || value.length !== length) return null;
  return value.every((entry) => boundedNumber(entry, -100_000, 100_000))
    ? value as number[]
    : null;
}

/** Runtime-check the exact persisted metric region before restoring an unresolved draft. */
export function parsePersistedRegionSelection(value: unknown): RegionSelection | null {
  const selection = record(value);
  const region = record(selection?.region);
  if (!selection || !region) return null;
  const target = selection.target;
  const surfaceAxis = selection.surface_axis;
  const surfaceSign = selection.surface_sign;
  if (!(target === undefined || target === null || (typeof target === "string" && target.length <= 64))) return null;
  if (!(surfaceAxis === undefined || surfaceAxis === null || surfaceAxis === "x" || surfaceAxis === "y" || surfaceAxis === "z")) return null;
  if (!(surfaceSign === undefined || surfaceSign === null || surfaceSign === "+" || surfaceSign === "-")) return null;

  if (region.kind === "box") {
    const min = point(region.min_mm, 3);
    const max = point(region.max_mm, 3);
    if (!min || !max || max.some((entry, index) => entry <= min[index])) return null;
  } else if (region.kind === "lasso") {
    if (!(region.axis === "x" || region.axis === "y" || region.axis === "z")) return null;
    if (!boundedNumber(region.offset_mm, -100_000, 100_000)) return null;
    if (!boundedNumber(region.depth_mm, Number.MIN_VALUE, 10_000)) return null;
    if (!Array.isArray(region.points_mm) || region.points_mm.length < 3 || region.points_mm.length > 256) return null;
    const points = region.points_mm.map((entry) => point(entry, 2));
    if (points.some((entry) => entry === null)) return null;
    const validPoints = points as number[][];
    const xs = validPoints.map((entry) => entry[0]);
    const ys = validPoints.map((entry) => entry[1]);
    if (Math.max(...xs) <= Math.min(...xs) || Math.max(...ys) <= Math.min(...ys)) return null;
  } else {
    return null;
  }
  return value as RegionSelection;
}

/** A restorable card is only the exact draft child described by its server-owned snapshot. */
export function restorableLocalEditDraft(version: Version): RestorableLocalEditDraft | null {
  if (version.state !== "draft" || !version.parent_version_id) return null;
  const provenance = record(version.provenance);
  const snapshot = record(provenance?.local_edit);
  const command = snapshot?.command;
  const region = parsePersistedRegionSelection(snapshot?.region);
  if (
    provenance?.operation !== "ai_command"
    || !snapshot
    || snapshot.schema_version !== 1
    || typeof provenance.ai_request_id !== "string"
    || snapshot.ai_request_id !== provenance.ai_request_id
    || snapshot.source_version_id !== version.parent_version_id
    || typeof command !== "string"
    || command.trim().length === 0
    || command.length > 4_000
    || !region
  ) return null;
  return { version, sourceVersionId: version.parent_version_id, command, region };
}

/** Version lists are newest-first today, but sequence comparison keeps recovery deterministic. */
export function latestRestorableLocalEditDraft(
  versions: readonly Version[],
): RestorableLocalEditDraft | null {
  return versions
    .map(restorableLocalEditDraft)
    .filter((entry): entry is RestorableLocalEditDraft => entry !== null)
    .sort((left, right) => right.version.sequence_no - left.version.sequence_no)[0] ?? null;
}
