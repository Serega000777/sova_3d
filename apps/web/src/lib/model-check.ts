import {
  parseIntegrityReport,
  type IntegrityReport,
  type IntegrityReportRecord,
  type Job,
} from "@physical-ai/contracts";

export type ModelCheckGroupStatus = "pass" | "warn" | "fail" | "unknown";

export const MODEL_CHECK_GROUPS = {
  geometry: ["coordinates_finite", "surface_area", "volume", "watertight", "face_count"],
  scene: ["scene_node_count", "scene_mesh_count", "animation_count", "camera_count", "light_count"],
  appearance: ["material_count", "texture_count"],
  scale: ["bbox_size", "units_explicit"],
} as const;

/** Only the ordinary, non-printable GLB conversion is the canonical model integrity check. */
export function parseOrdinaryModelCheck(value: unknown): IntegrityReport | null {
  const report = parseIntegrityReport(value);
  return report
    && report.targetFormat === "glb"
    && report.output.format === "glb"
    && report.printableGate === false
    ? report
    : null;
}

/** Bind a completed export to the exact immutable version and terminal outcome. */
export function verifiedModelCheckJob(job: Job, versionId: string): IntegrityReport | null {
  if (job.type !== "export" || job.project_version_id !== versionId) return null;
  const result = job.result as { report?: unknown; format?: unknown; printable_gate?: unknown } | null;
  const failure = job.error as { details?: { report?: unknown } } | null;
  if (job.status === "succeeded") {
    if (result?.format !== "glb" || result.printable_gate !== false) return null;
    const report = parseOrdinaryModelCheck(result.report);
    return report && report.status !== "fail" ? report : null;
  }
  if (job.status === "failed") {
    const report = parseOrdinaryModelCheck(failure?.details?.report);
    return report?.status === "fail" ? report : null;
  }
  return null;
}

/** A post-run read must resolve to the job that just finished, not an older report. */
export function verifiedPersistedModelCheck(
  record: IntegrityReportRecord,
  expectedJobId?: string,
): IntegrityReport | null {
  if (expectedJobId && record.job_id !== expectedJobId) return null;
  return parseOrdinaryModelCheck(record.report);
}

export function modelCheckGroupStatus(
  report: IntegrityReport,
  ids: readonly string[],
): ModelCheckGroupStatus {
  const checks = report.checks.filter((check) => ids.includes(check.id));
  if (checks.length === 0) return "unknown";
  if (checks.some((check) => check.status === "fail")) return "fail";
  return checks.some((check) => check.status === "warn") ? "warn" : "pass";
}
