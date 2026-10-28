import type { Job, Scan, Version } from "@physical-ai/contracts";

export interface PhysicalComparisonReport {
  ok: true;
  registration_transform: number[];
  registration_rms_mm: number;
  tolerance_mm: number;
  mean_mm: number;
  p95_mm: number;
  max_mm: number;
  within_tolerance: number;
  samples: number;
  design_size_mm: number[];
  scan_size_mm: number[];
  size_error_mm: number[];
  scale_locked: true;
}

function finite(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum;
}

function vector(value: unknown, length: number, positive = false): value is number[] {
  return Array.isArray(value)
    && value.length === length
    && value.every((item) => finite(item, positive ? Number.EPSILON : -Number.MAX_VALUE));
}

/** Bind metrology evidence to the exact design, accepted scan and requested measurement budget. */
export function verifiedPhysicalComparison(
  job: Job,
  designVersionId: string,
  scanVersionId: string,
  toleranceMm: number,
  samples: number,
): PhysicalComparisonReport | null {
  const result = job.result as {
    design_version_id?: unknown;
    scan_version_id?: unknown;
    scan_session_id?: unknown;
    report?: unknown;
  } | null;
  if (
    job.status !== "succeeded"
    || job.type !== "physical_compare"
    || job.project_version_id !== designVersionId
    || result?.design_version_id !== designVersionId
    || result.scan_version_id !== scanVersionId
    || typeof result.scan_session_id !== "string"
    || result.scan_session_id.trim() === ""
    || !result.report
    || typeof result.report !== "object"
    || Array.isArray(result.report)
  ) return null;
  const report = result.report as Record<string, unknown>;
  if (
    report.ok !== true
    || report.scale_locked !== true
    || report.tolerance_mm !== toleranceMm
    || report.samples !== samples
    || !vector(report.registration_transform, 16)
    || !finite(report.registration_rms_mm)
    || !finite(report.mean_mm)
    || !finite(report.p95_mm)
    || !finite(report.max_mm)
    || (report.mean_mm as number) > (report.p95_mm as number)
    || (report.p95_mm as number) > (report.max_mm as number)
    || !finite(report.within_tolerance)
    || (report.within_tolerance as number) > 1
    || !vector(report.design_size_mm, 3, true)
    || !vector(report.scan_size_mm, 3, true)
    || !vector(report.size_error_mm, 3)
  ) return null;
  for (let axis = 0; axis < 3; axis += 1) {
    const expected = (report.scan_size_mm as number[])[axis]! - (report.design_size_mm as number[])[axis]!;
    if (Math.abs(expected - (report.size_error_mm as number[])[axis]!) > 0.002) return null;
  }
  return report as unknown as PhysicalComparisonReport;
}

export function acceptedScanResults(scans: readonly Scan[]): Map<string, Scan> {
  return new Map(
    scans
      .filter((scan): scan is Scan & { result_version_id: string } => (
        scan.status === "accepted" && typeof scan.result_version_id === "string"
      ))
      .map((scan) => [scan.result_version_id, scan]),
  );
}

export function physicalComparisonModelAsset(
  version: Pick<Version, "assets">,
): { assetId: string; format: "stl" | "glb" } | null {
  const preview = version.assets.find((asset) => asset.role === "preview");
  if (preview) return { assetId: preview.asset_id, format: "glb" };
  const model = version.assets.find((asset) => asset.role === "model")
    ?? version.assets.find((asset) => asset.role === "scan");
  return model ? { assetId: model.asset_id, format: "stl" } : null;
}
