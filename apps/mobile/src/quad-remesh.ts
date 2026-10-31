import type { Job } from "@physical-ai/contracts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/;

export type QuadTargetFaces =
  | { ok: true; value: number }
  | { ok: false };

export interface VerifiedQuadRemesh {
  assetId: string;
  byteSize: number;
  sourceVersionId: string;
  targetFaces: number;
  report: {
    blenderVersion: string;
    faces: number;
    quadFaces: number;
    triangleFaces: number;
    otherFaces: number;
    vertices: number;
    quadRatio: number;
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function parseQuadTargetFaces(value: string): QuadTargetFaces {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) return { ok: false };
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed >= 100 && parsed <= 100_000
    ? { ok: true, value: parsed }
    : { ok: false };
}

/** Bind the mobile download surface to the exact immutable version, request and sandbox report.
 * QuadriFlow is quad-dominant rather than guaranteed all-quad, so a valid ratio may be below 1. */
export function verifiedQuadRemeshJob(
  job: Job,
  versionId: string,
  targetFaces: number,
): VerifiedQuadRemesh | null {
  if (
    job.type !== "quad_remesh"
    || job.status !== "succeeded"
    || job.project_version_id !== versionId
    || !Number.isSafeInteger(targetFaces)
    || targetFaces < 100
    || targetFaces > 100_000
  ) return null;

  const result = record(job.result);
  const report = record(result?.report);
  if (!result || !report) return null;

  const faces = report.faces;
  const quadFaces = report.quad_faces;
  const triangleFaces = report.triangle_faces;
  const otherFaces = report.other_faces;
  const vertices = report.vertices;
  const quadRatio = report.quad_ratio;
  const faceCounts = [faces, quadFaces, triangleFaces, otherFaces, vertices];
  if (
    typeof result.asset_id !== "string"
    || !UUID.test(result.asset_id)
    || result.format !== "fbx"
    || !Number.isSafeInteger(result.byte_size)
    || (result.byte_size as number) <= 0
    || result.source_version_id !== versionId
    || result.target_faces !== targetFaces
    || report.schema_version !== 1
    || report.operation !== "quad_remesh"
    || report.target_faces !== targetFaces
    || typeof report.blender_version !== "string"
    || report.blender_version.length < 1
    || report.blender_version.length > 80
    || faceCounts.some((value) => !Number.isSafeInteger(value))
    || (faces as number) < 1
    || (faces as number) > 200_000
    || (quadFaces as number) < 0
    || (triangleFaces as number) < 0
    || (otherFaces as number) < 0
    || (quadFaces as number) + (triangleFaces as number) + (otherFaces as number) !== faces
    || (vertices as number) < 1
    || (vertices as number) > 1_000_000
    || typeof quadRatio !== "number"
    || !Number.isFinite(quadRatio)
    || quadRatio < 0
    || quadRatio > 1
    || Math.abs(quadRatio - Number(((quadFaces as number) / (faces as number)).toFixed(4))) > 1e-9
    || typeof report.source_sha256 !== "string"
    || !SHA256.test(report.source_sha256)
    || typeof report.script_sha256 !== "string"
    || !SHA256.test(report.script_sha256)
    || !Array.isArray(report.sandbox_network_interfaces)
    || report.sandbox_network_interfaces.length !== 1
    || report.sandbox_network_interfaces[0] !== "lo"
    || report.sandbox_uid !== 65_534
    || report.capability_effective !== "0000000000000000"
    || report.capability_permitted !== "0000000000000000"
    || report.capability_ambient !== "0000000000000000"
    || report.no_new_privileges !== true
  ) return null;

  return {
    assetId: result.asset_id,
    byteSize: result.byte_size as number,
    sourceVersionId: versionId,
    targetFaces,
    report: {
      blenderVersion: report.blender_version,
      faces: faces as number,
      quadFaces: quadFaces as number,
      triangleFaces: triangleFaces as number,
      otherFaces: otherFaces as number,
      vertices: vertices as number,
      quadRatio,
    },
  };
}
