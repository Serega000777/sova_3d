/** Runtime-safe view of the existing mesh-repair job result (T-031). */

export interface MeshRepairStats {
  /** Boundary loops reported by the repair worker. */
  holes: number;
  /** Connected mesh bodies; shown to people as disconnected fragments. */
  fragments: number;
  /** Boundary breaks where more than two faces share an edge. */
  surfaceBreaks: number;
  /** Degenerate/duplicate faces, unreferenced vertices and invalid vertices. */
  noise: number;
  /** Winding/inversion issues that can be repaired without inventing geometry. */
  normalIssues: number;
}

export interface MeshDefectSummary {
  kind: "large_hole" | "floating_fragment" | "surface_break" | "noise_fragment" | "normal_issue";
  count: number;
  repairStep: "holes" | "degenerate" | "normals" | "fragments" | null;
}

export interface MeshRepairReportSummary {
  changed: boolean;
  before: MeshRepairStats;
  after: MeshRepairStats;
  holesClosed: number;
  fragmentsRemoved: number;
  fragmentMaxSizeMm: number | null;
  defectsBefore: MeshDefectSummary[];
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

function fragmentSize(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0.1 && value <= 1000
    ? value
    : null;
}

function repairStats(value: Record<string, unknown>): MeshRepairStats | null {
  const holes = nonNegativeInteger(value.holes);
  const fragments = nonNegativeInteger(value.bodies);
  const optionalCount = (key: string) =>
    value[key] === undefined ? 0 : nonNegativeInteger(value[key]);
  const surfaceBreaks = optionalCount("non_manifold_edges");
  const degenerateFaces = optionalCount("degenerate_faces");
  const duplicateFaces = optionalCount("duplicate_faces");
  const unreferencedVertices = optionalCount("unreferenced_vertices");
  const nanVertices = optionalCount("nan_vertices");
  const windingConsistent = value.winding_consistent === undefined ? true : value.winding_consistent;
  const inverted = value.inverted === undefined ? false : value.inverted;
  if (
    holes === null ||
    fragments === null ||
    surfaceBreaks === null ||
    degenerateFaces === null ||
    duplicateFaces === null ||
    unreferencedVertices === null ||
    nanVertices === null ||
    typeof windingConsistent !== "boolean" ||
    typeof inverted !== "boolean"
  ) return null;
  return {
    holes,
    fragments,
    surfaceBreaks,
    noise: degenerateFaces + duplicateFaces + unreferencedVertices + nanVertices,
    normalIssues: Number(!windingConsistent) + Number(inverted),
  };
}

function defectSummary(stats: MeshRepairStats): MeshDefectSummary[] {
  const defects: MeshDefectSummary[] = [
    { kind: "large_hole", count: stats.holes, repairStep: "holes" },
    { kind: "floating_fragment", count: Math.max(stats.fragments - 1, 0), repairStep: "fragments" },
    { kind: "surface_break", count: stats.surfaceBreaks, repairStep: null },
    { kind: "noise_fragment", count: stats.noise, repairStep: "degenerate" },
    { kind: "normal_issue", count: stats.normalIssues, repairStep: "normals" },
  ];
  return defects.filter((defect) => defect.count > 0);
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
  const beforeStats = repairStats(before);
  const afterStats = repairStats(after);
  if (!beforeStats || !afterStats) return null;
  const delta = raw.delta;
  const holesClosed =
    delta && typeof delta === "object"
      ? nonNegativeInteger((delta as Record<string, unknown>).holes_closed)
      : null;
  if (holesClosed === null) return null;
  const fragmentsRemoved =
    delta && typeof delta === "object" && "bodies_removed" in delta
      ? nonNegativeInteger((delta as Record<string, unknown>).bodies_removed)
      : 0;
  if (fragmentsRemoved === null) return null;
  const rawFragmentSize = raw.fragment_max_size_mm;
  const fragmentMaxSizeMm =
    rawFragmentSize === undefined || rawFragmentSize === null ? null : fragmentSize(rawFragmentSize);
  if (rawFragmentSize !== undefined && rawFragmentSize !== null && fragmentMaxSizeMm === null) {
    return null;
  }
  return {
    changed: raw.changed,
    before: beforeStats,
    after: afterStats,
    holesClosed,
    fragmentsRemoved,
    fragmentMaxSizeMm,
    defectsBefore: defectSummary(beforeStats),
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
