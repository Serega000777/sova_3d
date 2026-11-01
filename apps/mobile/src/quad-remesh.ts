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
    sourceUvLayers: number | null;
    uvLayers: number | null;
    uvCoordinates: number | null;
    uvBounds: [number, number, number, number] | null;
    uvTransfer: "none" | "active_surface_projected" | null;
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

  const schemaVersion = report.schema_version;
  // v3 moved UV evidence into one per_object entry; the mobile surface still only displays
  // one object's worth of detail, so a multi-object scene result is honestly left unverified
  // here rather than flattening/guessing which object's evidence to show.
  let uvSource: Record<string, unknown> = report;
  if (schemaVersion === 3) {
    if (report.objects !== 1 || !Array.isArray(report.per_object) || report.per_object.length !== 1) {
      return null;
    }
    const only = record(report.per_object[0]);
    if (!only) return null;
    uvSource = only;
  }

  const faces = report.faces;
  const quadFaces = report.quad_faces;
  const triangleFaces = report.triangle_faces;
  const otherFaces = report.other_faces;
  const vertices = report.vertices;
  const quadRatio = report.quad_ratio;
  const uvBounds = uvSource.uv_bounds;
  const uvEvidenceValid = schemaVersion === 1 || (
    (schemaVersion === 2 || schemaVersion === 3)
    && Number.isSafeInteger(uvSource.source_uv_layers)
    && (uvSource.source_uv_layers as number) >= 0
    && (uvSource.source_uv_layers as number) <= 16
    && Number.isSafeInteger(uvSource.uv_layers)
    && ((uvSource.source_uv_layers as number) > 0 ? uvSource.uv_layers === 1 : uvSource.uv_layers === 0)
    && Number.isSafeInteger(uvSource.uv_coordinates)
    && ((uvSource.uv_layers as number) > 0 ? (uvSource.uv_coordinates as number) > 0 : uvSource.uv_coordinates === 0)
    && (uvSource.uv_coordinates as number) <= 4_000_000
    && (
      uvSource.uv_layers === 0
        ? uvBounds === null && uvSource.uv_transfer === "none"
        : Array.isArray(uvBounds)
          && uvBounds.length === 4
          && uvBounds.every((value) => typeof value === "number" && Number.isFinite(value))
          && uvBounds[0] <= uvBounds[2]
          && uvBounds[1] <= uvBounds[3]
          && uvSource.uv_transfer === "active_surface_projected"
    )
  );
  const faceCounts = [faces, quadFaces, triangleFaces, otherFaces, vertices];
  if (
    typeof result.asset_id !== "string"
    || !UUID.test(result.asset_id)
    || result.format !== "fbx"
    || !Number.isSafeInteger(result.byte_size)
    || (result.byte_size as number) <= 0
    || result.source_version_id !== versionId
    || result.target_faces !== targetFaces
    || !uvEvidenceValid
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
      sourceUvLayers: schemaVersion === 2 || schemaVersion === 3
        ? uvSource.source_uv_layers as number
        : null,
      uvLayers: schemaVersion === 2 || schemaVersion === 3 ? uvSource.uv_layers as number : null,
      uvCoordinates: schemaVersion === 2 || schemaVersion === 3
        ? uvSource.uv_coordinates as number
        : null,
      uvBounds: (schemaVersion === 2 || schemaVersion === 3) && Array.isArray(uvBounds)
        ? uvBounds as [number, number, number, number]
        : null,
      uvTransfer: schemaVersion === 2 || schemaVersion === 3
        ? uvSource.uv_transfer as "none" | "active_surface_projected"
        : null,
    },
  };
}
