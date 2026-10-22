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

export interface MeshDefectInstance extends MeshDefectSummary {
  id: string;
  centerMm: [number, number, number];
  sizeMm: number;
}

export interface MeshRepairReportSummary {
  changed: boolean;
  before: MeshRepairStats;
  after: MeshRepairStats;
  holesClosed: number;
  fragmentsRemoved: number;
  fragmentMaxSizeMm: number | null;
  defectsBefore: MeshDefectSummary[];
  defectInstances: MeshDefectInstance[];
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

const defectKinds = new Set<MeshDefectSummary["kind"]>([
  "large_hole",
  "floating_fragment",
  "surface_break",
  "noise_fragment",
  "normal_issue",
]);

function repairStep(kind: MeshDefectSummary["kind"]): MeshDefectSummary["repairStep"] {
  if (kind === "large_hole") return "holes";
  if (kind === "floating_fragment") return "fragments";
  if (kind === "noise_fragment") return "degenerate";
  if (kind === "normal_issue") return "normals";
  return null;
}

function defectInstances(value: unknown): MeshDefectInstance[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 512) return null;
  const parsed: MeshDefectInstance[] = [];
  const ids = new Set<string>();
  for (const entry of value) {
    if (!entry || typeof entry !== "object") return null;
    const raw = entry as Record<string, unknown>;
    if (typeof raw.kind !== "string" || !defectKinds.has(raw.kind as MeshDefectSummary["kind"])) {
      return null;
    }
    const kind = raw.kind as MeshDefectSummary["kind"];
    if (
      typeof raw.id !== "string" ||
      !new RegExp(`^${kind}:[0-9a-f]{20}$`).test(raw.id) ||
      ids.has(raw.id) ||
      !Array.isArray(raw.center_mm) ||
      raw.center_mm.length !== 3 ||
      raw.center_mm.some((coordinate) => typeof coordinate !== "number" || !Number.isFinite(coordinate)) ||
      typeof raw.size_mm !== "number" ||
      !Number.isFinite(raw.size_mm) ||
      raw.size_mm < 0
    ) return null;
    const count = nonNegativeInteger(raw.count);
    if (count === null || count < 1) return null;
    ids.add(raw.id);
    parsed.push({
      id: raw.id,
      kind,
      count,
      repairStep: repairStep(kind),
      centerMm: raw.center_mm as [number, number, number],
      sizeMm: raw.size_mm,
    });
  }
  return parsed;
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
  const instances = defectInstances(raw.remaining_defects ?? raw.detected_defects);
  if (instances === null) return null;
  return {
    changed: raw.changed,
    before: beforeStats,
    after: afterStats,
    holesClosed,
    fragmentsRemoved,
    fragmentMaxSizeMm,
    defectsBefore: defectSummary(beforeStats),
    defectInstances: instances,
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
