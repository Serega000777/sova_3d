import {
  parseIntegrityReport,
  type IntegrityReport,
  type Job,
} from "@physical-ai/contracts";

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

/** Bind a newly completed check to the exact immutable version and terminal job outcome. */
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
