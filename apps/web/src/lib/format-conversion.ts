import {
  parseIntegrityReport,
  type Download,
  type IntegrityReport,
  type Job,
} from "@physical-ai/contracts";

export interface VerifiedExchangeConversion {
  assetId: string;
  byteSize: number;
  format: string;
  report: IntegrityReport;
}

export interface VerifiedExchangeDownload {
  assetId: string;
  byteSize: number;
  format: string;
  url: string;
}

/** Bind a downloadable exchange file to the exact immutable version, requested format and gate. */
export function verifiedExchangeConversion(
  job: Job,
  requestedVersionId: string,
  requestedFormat: string,
  printableGate: boolean,
): VerifiedExchangeConversion | null {
  if (
    job.type !== "export"
    || job.status !== "succeeded"
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
    format: requestedFormat,
    report,
  };
}

/** Accept only the signed download for the exact asset bytes verified by the export job. */
export function verifiedExchangeDownload(
  conversion: Pick<VerifiedExchangeConversion, "assetId" | "byteSize" | "format">,
  download: Download,
): VerifiedExchangeDownload | null {
  if (
    download.asset_id !== conversion.assetId
    || download.format !== conversion.format
    || download.byte_size !== conversion.byteSize
    || typeof download.url !== "string"
    || download.url.trim() === ""
  ) return null;
  try {
    const parsed = new URL(download.url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  } catch {
    return null;
  }
  return {
    assetId: conversion.assetId,
    byteSize: conversion.byteSize,
    format: conversion.format,
    url: download.url,
  };
}
