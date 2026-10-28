import {
  parseIntegrityReport,
  type IntegrityReport,
  type Job,
} from "@physical-ai/contracts";

export interface VerifiedExchangeConversion {
  assetId: string;
  byteSize: number;
  report: IntegrityReport;
}

/** Bind a downloadable exchange file to the exact immutable version, requested format and gate. */
export function verifiedExchangeConversion(
  job: Job,
  requestedVersionId: string,
  requestedFormat: string,
  printableGate: boolean,
): VerifiedExchangeConversion | null {
  if (
    job.status !== "succeeded"
    || job.project_version_id !== requestedVersionId
    || !job.result
    || typeof job.result.asset_id !== "string"
    || job.result.asset_id.trim() === ""
    || job.result.format !== requestedFormat
    || !Number.isInteger(job.result.byte_size)
    || (job.result.byte_size as number) <= 0
    || job.result.printable_gate !== printableGate
  ) return null;

  const report = parseIntegrityReport(job.result.report);
  if (
    !report
    || report.status === "fail"
    || report.targetFormat !== requestedFormat
    || report.output.format !== requestedFormat
    || report.printableGate !== printableGate
  ) return null;

  return {
    assetId: job.result.asset_id,
    byteSize: job.result.byte_size as number,
    report,
  };
}
