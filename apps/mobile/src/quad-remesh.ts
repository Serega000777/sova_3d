import type { Job } from "@physical-ai/contracts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_OBJECTS = 64;

export type QuadTargetFaces =
  | { ok: true; value: number }
  | { ok: false };

export interface QuadRemeshObjectEvidence {
  name: string | null;
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
  materials: QuadRemeshMaterialEvidence[] | null;
  materialTransfer: "none" | "single_slot_preserved" | "nearest_source_polygon" | null;
}

export interface QuadRemeshMaterialEvidence {
  name: string;
  diffuseRgba: [number, number, number, number];
  textureSha256s: string[];
  sourceFaces: number;
  outputFaces: number;
}

export interface VerifiedQuadRemesh {
  assetId: string;
  byteSize: number;
  sourceVersionId: string;
  targetFaces: number;
  /** The whole report's aggregate (sum across every object for schema v3/v4). */
  report: QuadRemeshObjectEvidence & { blenderVersion: string };
  /** One entry per remeshed object; always at least one. Only schema v3/v4 can report more
   *  than one — a v1/v2 report is exactly this same aggregate as its single object. */
  objects: QuadRemeshObjectEvidence[];
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

/** One object's face counts + UV/material evidence, shared by the v1/v2 whole report and every
 *  schema v3/v4 per_object entry. `hasUvFields` is false only for schema v1, which predates UV
 *  transfer entirely and carries no such evidence one way or the other. */
function parseObjectEvidence(
  source: Record<string, unknown>,
  hasUvFields: boolean,
  hasMaterialFields: boolean,
  faceUpperBound: number,
  vertexUpperBound: number,
): QuadRemeshObjectEvidence | null {
  const faces = source.faces;
  const quadFaces = source.quad_faces;
  const triangleFaces = source.triangle_faces;
  const otherFaces = source.other_faces;
  const vertices = source.vertices;
  const quadRatio = source.quad_ratio;
  const faceCounts = [faces, quadFaces, triangleFaces, otherFaces, vertices];
  if (faceCounts.some((value) => !Number.isSafeInteger(value))) return null;
  if ((faces as number) < 1 || (faces as number) > faceUpperBound) return null;
  if ((quadFaces as number) < 0 || (triangleFaces as number) < 0 || (otherFaces as number) < 0) {
    return null;
  }
  if ((quadFaces as number) + (triangleFaces as number) + (otherFaces as number) !== faces) {
    return null;
  }
  if ((vertices as number) < 1 || (vertices as number) > vertexUpperBound) return null;
  if (typeof quadRatio !== "number" || !Number.isFinite(quadRatio) || quadRatio < 0 || quadRatio > 1) {
    return null;
  }
  if (Math.abs(quadRatio - Number(((quadFaces as number) / (faces as number)).toFixed(4))) > 1e-9) {
    return null;
  }

  if (!hasUvFields) {
    return {
      name: null,
      faces: faces as number,
      quadFaces: quadFaces as number,
      triangleFaces: triangleFaces as number,
      otherFaces: otherFaces as number,
      vertices: vertices as number,
      quadRatio,
      sourceUvLayers: null,
      uvLayers: null,
      uvCoordinates: null,
      uvBounds: null,
      uvTransfer: null,
      materials: null,
      materialTransfer: null,
    };
  }

  const uvBounds = source.uv_bounds;
  const sourceUvLayers = source.source_uv_layers;
  const uvLayers = source.uv_layers;
  const uvCoordinates = source.uv_coordinates;
  const uvEvidenceValid = (
    Number.isSafeInteger(sourceUvLayers)
    && (sourceUvLayers as number) >= 0
    && (sourceUvLayers as number) <= 16
    && Number.isSafeInteger(uvLayers)
    && ((sourceUvLayers as number) > 0 ? uvLayers === 1 : uvLayers === 0)
    && Number.isSafeInteger(uvCoordinates)
    && ((uvLayers as number) > 0 ? (uvCoordinates as number) > 0 : uvCoordinates === 0)
    && (uvCoordinates as number) <= 4_000_000
    && (
      uvLayers === 0
        ? uvBounds === null && source.uv_transfer === "none"
        : Array.isArray(uvBounds)
          && uvBounds.length === 4
          && uvBounds.every((value) => typeof value === "number" && Number.isFinite(value))
          && uvBounds[0] <= uvBounds[2]
          && uvBounds[1] <= uvBounds[3]
          && source.uv_transfer === "active_surface_projected"
    )
  );
  if (!uvEvidenceValid) return null;

  let materials: QuadRemeshMaterialEvidence[] | null = null;
  let materialTransfer: QuadRemeshObjectEvidence["materialTransfer"] = null;
  if (hasMaterialFields) {
    const rawMaterials = source.materials;
    const rawTransfer = source.material_transfer;
    if (!Array.isArray(rawMaterials) || rawMaterials.length > 64) return null;
    const parsed: QuadRemeshMaterialEvidence[] = [];
    for (const raw of rawMaterials) {
      const material = record(raw);
      const rgba = material?.diffuse_rgba;
      const digests = material?.texture_sha256s;
      const sourceFaces = material?.source_faces;
      const outputFaces = material?.output_faces;
      if (
        !material
        || typeof material.name !== "string"
        || material.name.length < 1
        || material.name.length > 200
        || !Array.isArray(rgba)
        || rgba.length !== 4
        || rgba.some((value) => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1)
        || !Array.isArray(digests)
        || digests.length > 32
        || digests.some((value) => typeof value !== "string" || !SHA256.test(value))
        || new Set(digests).size !== digests.length
        || [...digests].sort().some((value, index) => value !== digests[index])
        || !Number.isSafeInteger(sourceFaces)
        || (sourceFaces as number) < 0
        || (sourceFaces as number) > 300_000
        || !Number.isSafeInteger(outputFaces)
        || (outputFaces as number) < 0
        || (outputFaces as number) > 200_000
      ) return null;
      parsed.push({
        name: material.name,
        diffuseRgba: rgba as [number, number, number, number],
        textureSha256s: digests as string[],
        sourceFaces: sourceFaces as number,
        outputFaces: outputFaces as number,
      });
    }
    const expectedTransfer = parsed.length === 0
      ? "none"
      : parsed.length === 1
        ? "single_slot_preserved"
        : "nearest_source_polygon";
    if (rawTransfer !== expectedTransfer) return null;
    if (parsed.length > 0 && parsed.reduce((total, material) => total + material.outputFaces, 0) !== faces) {
      return null;
    }
    if (parsed.some((material) => material.textureSha256s.length > 0) && sourceUvLayers === 0) {
      return null;
    }
    materials = parsed;
    materialTransfer = expectedTransfer;
  }

  const name = source.name;
  return {
    name: typeof name === "string" && name.length > 0 ? name : null,
    faces: faces as number,
    quadFaces: quadFaces as number,
    triangleFaces: triangleFaces as number,
    otherFaces: otherFaces as number,
    vertices: vertices as number,
    quadRatio,
    sourceUvLayers: sourceUvLayers as number,
    uvLayers: uvLayers as number,
    uvCoordinates: uvCoordinates as number,
    uvBounds: Array.isArray(uvBounds) ? (uvBounds as [number, number, number, number]) : null,
    uvTransfer: source.uv_transfer as "none" | "active_surface_projected",
    materials,
    materialTransfer,
  };
}

/** Bind the mobile download surface to the exact immutable version, request and sandbox report.
 * QuadriFlow is quad-dominant rather than guaranteed all-quad, so a valid ratio may be below 1.
 * A schema v3/v4 scene result carries one evidence entry per remeshed object; every entry (and the
 * aggregate's cross-sum against them) is verified, not just the first. */
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
  if (schemaVersion !== 1 && schemaVersion !== 2 && schemaVersion !== 3 && schemaVersion !== 4) return null;

  let objects: QuadRemeshObjectEvidence[];
  if (schemaVersion === 3 || schemaVersion === 4) {
    const objectCount = report.objects;
    const perObjectRaw = report.per_object;
    if (
      !Number.isSafeInteger(objectCount)
      || (objectCount as number) < 1
      || (objectCount as number) > MAX_OBJECTS
      || !Array.isArray(perObjectRaw)
      || perObjectRaw.length !== objectCount
    ) return null;
    const parsed: QuadRemeshObjectEvidence[] = [];
    const seenNames = new Set<string>();
    for (const entry of perObjectRaw) {
      const entryRecord = record(entry);
      if (!entryRecord) return null;
      const evidence = parseObjectEvidence(
        entryRecord,
        true,
        schemaVersion === 4,
        200_000,
        1_000_000,
      );
      if (!evidence || evidence.name === null || seenNames.has(evidence.name)) return null;
      seenNames.add(evidence.name);
      parsed.push(evidence);
    }
    objects = parsed;
    const aggregate = parseObjectEvidence(report, false, false, 12_800_000, 64_000_000);
    if (!aggregate) return null;
    const sum = (key: "faces" | "quadFaces" | "triangleFaces" | "otherFaces" | "vertices") =>
      objects.reduce((total, entry) => total + entry[key], 0);
    if (
      aggregate.faces !== sum("faces")
      || aggregate.quadFaces !== sum("quadFaces")
      || aggregate.triangleFaces !== sum("triangleFaces")
      || aggregate.otherFaces !== sum("otherFaces")
      || aggregate.vertices !== sum("vertices")
    ) return null;
  } else {
    const whole = parseObjectEvidence(report, schemaVersion === 2, false, 200_000, 1_000_000);
    if (!whole) return null;
    objects = [whole];
  }
  const aggregateFaces = objects.reduce((total, entry) => total + entry.faces, 0);
  const aggregateQuadFaces = objects.reduce((total, entry) => total + entry.quadFaces, 0);
  const aggregateTriangleFaces = objects.reduce((total, entry) => total + entry.triangleFaces, 0);
  const aggregateOtherFaces = objects.reduce((total, entry) => total + entry.otherFaces, 0);
  const aggregateVertices = objects.reduce((total, entry) => total + entry.vertices, 0);
  const aggregateQuadRatio = aggregateFaces > 0
    ? Number((aggregateQuadFaces / aggregateFaces).toFixed(4))
    : 0;

  if (
    typeof result.asset_id !== "string"
    || !UUID.test(result.asset_id)
    || result.format !== "fbx"
    || !Number.isSafeInteger(result.byte_size)
    || (result.byte_size as number) <= 0
    || result.source_version_id !== versionId
    || result.target_faces !== targetFaces
    || report.operation !== "quad_remesh"
    || report.target_faces !== targetFaces
    || typeof report.blender_version !== "string"
    || report.blender_version.length < 1
    || report.blender_version.length > 80
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
      name: null,
      faces: aggregateFaces,
      quadFaces: aggregateQuadFaces,
      triangleFaces: aggregateTriangleFaces,
      otherFaces: aggregateOtherFaces,
      vertices: aggregateVertices,
      quadRatio: aggregateQuadRatio,
      sourceUvLayers: objects.length === 1 ? objects[0]!.sourceUvLayers : null,
      uvLayers: objects.length === 1 ? objects[0]!.uvLayers : null,
      uvCoordinates: objects.length === 1 ? objects[0]!.uvCoordinates : null,
      uvBounds: objects.length === 1 ? objects[0]!.uvBounds : null,
      uvTransfer: objects.length === 1 ? objects[0]!.uvTransfer : null,
      materials: objects.length === 1 ? objects[0]!.materials : null,
      materialTransfer: objects.length === 1 ? objects[0]!.materialTransfer : null,
    },
    objects,
  };
}
