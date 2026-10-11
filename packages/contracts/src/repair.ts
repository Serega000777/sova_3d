/** Runtime-safe view of the existing mesh-repair job result (T-031). */

export interface MeshRepairStats {
  /** Boundary loops reported by the repair worker. */
  holes: number;
  /** Connected mesh bodies; shown to people as disconnected fragments. */
  fragments: number;
}

export interface MeshRepairReportSummary {
  changed: boolean;
  before: MeshRepairStats;
  after: MeshRepairStats;
  holesClosed: number;
}

export interface MeshRepairJobResult {
  versionId: string;
  sourceVersionId: string;
  report: MeshRepairReportSummary;
}

export interface VersionLineageNode {
  id: string;
  parent_version_id: string | null;
  provenance: Record<string, unknown>;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/** Reject malformed job/provenance data instead of displaying invented topology counts. */
export function parseMeshRepairReport(value: unknown): MeshRepairReportSummary | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.changed !== "boolean") return null;
  if (!raw.before || typeof raw.before !== "object" || !raw.after || typeof raw.after !== "object") {
    return null;
  }
  const before = raw.before as Record<string, unknown>;
  const after = raw.after as Record<string, unknown>;
  const beforeHoles = nonNegativeInteger(before.holes);
  const beforeFragments = nonNegativeInteger(before.bodies);
  const afterHoles = nonNegativeInteger(after.holes);
  const afterFragments = nonNegativeInteger(after.bodies);
  if (
    beforeHoles === null ||
    beforeFragments === null ||
    afterHoles === null ||
    afterFragments === null
  ) {
    return null;
  }
  const delta = raw.delta;
  const holesClosed =
    delta && typeof delta === "object"
      ? nonNegativeInteger((delta as Record<string, unknown>).holes_closed)
      : null;
  if (holesClosed === null) return null;
  return {
    changed: raw.changed,
    before: { holes: beforeHoles, fragments: beforeFragments },
    after: { holes: afterHoles, fragments: afterFragments },
    holesClosed,
  };
}

export function parseMeshRepairJobResult(value: unknown): MeshRepairJobResult | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (
    typeof raw.version_id !== "string" ||
    raw.version_id.trim() === "" ||
    typeof raw.source_version_id !== "string" ||
    raw.source_version_id.trim() === ""
  ) {
    return null;
  }
  const report = parseMeshRepairReport(raw.report);
  return report
    ? { versionId: raw.version_id, sourceVersionId: raw.source_version_id, report }
    : null;
}

/** A repair action is offered only for a version whose bounded ancestry reaches a real scan. */
export function isScanDerivedVersion(
  active: VersionLineageNode | null,
  versions: readonly VersionLineageNode[],
): boolean {
  if (!active) return false;
  const byId = new Map(versions.map((version) => [version.id, version]));
  const seen = new Set<string>();
  let current: VersionLineageNode | undefined = active;
  while (current && !seen.has(current.id) && seen.size <= versions.length) {
    seen.add(current.id);
    if (current.provenance.operation === "scan") return true;
    current = current.parent_version_id ? byId.get(current.parent_version_id) : undefined;
  }
  return false;
}
