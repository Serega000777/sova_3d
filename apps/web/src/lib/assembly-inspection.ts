import type { AssemblyInspection, Job } from "@physical-ai/contracts";
import type { ViewerScenePart } from "@/components/ModelViewer";

export type ExplodedPreview = { order: string[]; gapMm: number };

export type EnvelopeOverlap = {
  node_a_id: string;
  node_b_id: string;
  overlap_mm: [number, number, number];
};

export type MeshCollision = {
  node_a_id: string;
  node_b_id: string;
  interference_mm3: number;
  bbox_min_mm: [number, number, number];
  bbox_max_mm: [number, number, number];
};

export type CollisionUnavailable = {
  node_a_id: string;
  node_b_id: string;
  reason: "non_watertight" | "boolean_failed" | "candidate_limit";
};

export type GeometryInspection = {
  ok: true;
  component_count: number;
  scene_bbox_min_mm: [number, number, number];
  scene_bbox_max_mm: [number, number, number];
  components: Array<{
    node_id: string;
    bbox_min_mm: [number, number, number];
    bbox_max_mm: [number, number, number];
  }>;
  envelope_overlaps: EnvelopeOverlap[];
  mesh_collisions: MeshCollision[];
  collision_unavailable_pairs: CollisionUnavailable[];
  collision_status: "checked" | "unavailable";
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

const finiteVector3 = (value: unknown): value is [number, number, number] => (
  Array.isArray(value)
  && value.length === 3
  && value.every((item) => typeof item === "number" && Number.isFinite(item))
);

function finiteMatrix4(value: unknown): boolean {
  return Array.isArray(value)
    && value.length === 4
    && value.every((row) => Array.isArray(row)
      && row.length === 4
      && row.every((item) => typeof item === "number" && Number.isFinite(item)));
}

const nodePair = (value: unknown): value is { node_a_id: string; node_b_id: string } => {
  const pair = record(value);
  return typeof pair?.node_a_id === "string"
    && pair.node_a_id.length > 0
    && typeof pair.node_b_id === "string"
    && pair.node_b_id.length > 0
    && pair.node_a_id !== pair.node_b_id;
};

const pairKey = (value: { node_a_id: string; node_b_id: string }) => (
  value.node_a_id < value.node_b_id
    ? `${value.node_a_id}\u0000${value.node_b_id}`
    : `${value.node_b_id}\u0000${value.node_a_id}`
);

/** Bind canonical manifest/BOM facts to one immutable version before rendering them. */
export function verifiedAssemblyInspection(
  value: unknown,
  versionId: string,
): AssemblyInspection | null {
  const manifest = record(value);
  if (
    !manifest
    || manifest.version_id !== versionId
    || manifest.structure_validated !== true
    || manifest.constraints_status !== "not_modeled"
    || manifest.collision_status !== "not_checked"
    || !Number.isInteger(manifest.component_count)
    || Number(manifest.component_count) < 1
    || !Number.isInteger(manifest.visible_component_count)
    || !Number.isInteger(manifest.unique_geometry_count)
    || !Array.isArray(manifest.components)
    || !Array.isArray(manifest.bom)
    || !Array.isArray(manifest.exploded_order)
    || !Array.isArray(manifest.limitations)
    || manifest.limitations.length === 0
    || manifest.components.length !== manifest.component_count
    || !manifest.limitations.every((item) => typeof item === "string" && item.trim())
  ) return null;

  const components = manifest.components.map(record);
  if (components.some((item) => !item)) return null;
  const rows = components as Record<string, unknown>[];
  const ids = rows.map((item) => item.node_id);
  if (
    ids.some((id) => typeof id !== "string" || !id)
    || new Set(ids).size !== ids.length
    || rows.some((item, index) => (
      item.order !== index + 1
      || typeof item.source_node_id !== "string"
      || typeof item.name !== "string"
      || !item.name
      || typeof item.resolved_asset_id !== "string"
      || typeof item.effective_visible !== "boolean"
      || !finiteMatrix4(item.world_transform)
    ))
  ) return null;
  const visible = rows.filter((item) => item.effective_visible).map((item) => item.node_id);
  if (
    visible.length !== manifest.visible_component_count
    || JSON.stringify(visible) !== JSON.stringify(manifest.exploded_order)
    || new Set(rows.map((item) => item.resolved_asset_id)).size !== manifest.unique_geometry_count
  ) return null;

  const bySource = new Map<string, Record<string, unknown>[]>();
  for (const component of rows) {
    const sourceId = component.source_node_id as string;
    const source = rows.find((item) => item.node_id === sourceId);
    if (
      !source
      || (component.instance_of === null && sourceId !== component.node_id)
      || (typeof component.instance_of === "string" && component.instance_of !== sourceId)
      || (component.instance_of !== null && typeof component.instance_of !== "string")
      || source.source_node_id !== source.node_id
      || source.resolved_asset_id !== component.resolved_asset_id
    ) return null;
    const group = bySource.get(sourceId) ?? [];
    group.push(component);
    bySource.set(sourceId, group);
  }
  if (manifest.bom.length !== bySource.size) return null;
  const seenBomSources = new Set<string>();
  for (const raw of manifest.bom) {
    const item = record(raw);
    if (!item || typeof item.source_node_id !== "string") return null;
    const members = bySource.get(item.source_node_id);
    const source = rows.find((component) => component.node_id === item.source_node_id);
    if (
      seenBomSources.has(item.source_node_id)
      || !members
      || !source
      || item.name !== source.name
      || item.resolved_asset_id !== source.resolved_asset_id
      || item.quantity !== members.length
      || item.visible_quantity !== members.filter((member) => member.effective_visible).length
      || !Array.isArray(item.node_ids)
      || JSON.stringify(item.node_ids) !== JSON.stringify(members.map((member) => member.node_id))
    ) return null;
    seenBomSources.add(item.source_node_id);
  }
  return value as AssemblyInspection;
}

function parseGeometryInspection(
  value: unknown,
  expectedNodeIds: readonly string[],
): GeometryInspection | null {
  const result = record(value);
  if (
    !result
    || result.ok !== true
    || !Number.isInteger(result.component_count)
    || Number(result.component_count) < 1
  ) return null;
  const expectedNodes = new Set(expectedNodeIds);
  if (expectedNodes.size !== expectedNodeIds.length || expectedNodes.size !== Number(result.component_count)) return null;
  const sceneMin = result.scene_bbox_min_mm;
  const sceneMax = result.scene_bbox_max_mm;
  if (!finiteVector3(sceneMin) || !finiteVector3(sceneMax) || sceneMin.some((minimum, index) => minimum > sceneMax[index]!)) return null;
  if (!Array.isArray(result.components) || !Array.isArray(result.envelope_overlaps) || !Array.isArray(result.mesh_collisions) || !Array.isArray(result.collision_unavailable_pairs)) return null;
  const components: GeometryInspection["components"] = [];
  for (const [index, raw] of result.components.entries()) {
    const item = record(raw);
    const bboxMin = item?.bbox_min_mm;
    const bboxMax = item?.bbox_max_mm;
    if (
      item?.node_id !== expectedNodeIds[index]
      || !finiteVector3(bboxMin)
      || !finiteVector3(bboxMax)
      || bboxMin.some((minimum, axis) => minimum >= bboxMax[axis]!)
    ) return null;
    components.push({ node_id: item.node_id as string, bbox_min_mm: bboxMin, bbox_max_mm: bboxMax });
  }
  if (components.length !== expectedNodeIds.length) return null;

  const envelopes: EnvelopeOverlap[] = [];
  const envelopeKeys = new Set<string>();
  for (const raw of result.envelope_overlaps) {
    if (!nodePair(raw) || !expectedNodes.has(raw.node_a_id) || !expectedNodes.has(raw.node_b_id)) return null;
    const overlap = record(raw)?.overlap_mm;
    if (!finiteVector3(overlap) || overlap.some((item) => item <= 0)) return null;
    const key = pairKey(raw);
    if (envelopeKeys.has(key)) return null;
    envelopeKeys.add(key);
    envelopes.push({ ...raw, overlap_mm: overlap });
  }

  const collisions: MeshCollision[] = [];
  const collisionKeys = new Set<string>();
  for (const raw of result.mesh_collisions) {
    if (!nodePair(raw)) return null;
    const item = record(raw);
    const bboxMin = item?.bbox_min_mm;
    const bboxMax = item?.bbox_max_mm;
    const interference = item?.interference_mm3;
    const key = pairKey(raw);
    if (
      typeof interference !== "number"
      || !Number.isFinite(interference)
      || interference <= 0
      || !finiteVector3(bboxMin)
      || !finiteVector3(bboxMax)
      || bboxMin.some((minimum, index) => minimum >= bboxMax[index]!)
      || !envelopeKeys.has(key)
      || collisionKeys.has(key)
    ) return null;
    collisionKeys.add(key);
    collisions.push({ ...raw, interference_mm3: interference, bbox_min_mm: bboxMin, bbox_max_mm: bboxMax });
  }

  const unavailable: CollisionUnavailable[] = [];
  const unavailableKeys = new Set<string>();
  for (const raw of result.collision_unavailable_pairs) {
    if (!nodePair(raw)) return null;
    const reason = record(raw)?.reason;
    const key = pairKey(raw);
    if (
      !(["non_watertight", "boolean_failed", "candidate_limit"] as unknown[]).includes(reason)
      || !envelopeKeys.has(key)
      || collisionKeys.has(key)
      || unavailableKeys.has(key)
    ) return null;
    unavailableKeys.add(key);
    unavailable.push({ ...raw, reason: reason as CollisionUnavailable["reason"] });
  }
  if (
    (result.collision_status === "checked" && unavailable.length !== 0)
    || (result.collision_status === "unavailable" && unavailable.length === 0)
    || (result.collision_status !== "checked" && result.collision_status !== "unavailable")
  ) return null;
  return {
    ok: true,
    component_count: Number(result.component_count),
    scene_bbox_min_mm: sceneMin,
    scene_bbox_max_mm: sceneMax,
    components,
    envelope_overlaps: envelopes,
    mesh_collisions: collisions,
    collision_unavailable_pairs: unavailable,
    collision_status: result.collision_status,
  };
}

export function verifiedAssemblyGeometryJob(
  job: Job,
  acceptedJobId: string,
  workspaceId: string,
  versionId: string,
  expectedNodeIds: readonly string[],
): GeometryInspection | null {
  if (
    job.id !== acceptedJobId
    || job.status !== "succeeded"
    || job.type !== "inspect_assembly_geometry"
    || job.workspace_id !== workspaceId
    || job.project_version_id !== versionId
  ) return null;
  const result = record(job.result);
  if (result?.version_id !== versionId || result.constraints_status !== "not_modeled") return null;
  return parseGeometryInspection(result, expectedNodeIds);
}

/** Reversible view-only offset along global Z; saved scene transforms are never mutated. */
export function applyExplodedPreview(
  parts: readonly ViewerScenePart[],
  preview: ExplodedPreview | null,
): ViewerScenePart[] {
  if (!preview || preview.order.length < 2 || !Number.isFinite(preview.gapMm) || preview.gapMm <= 0) return [...parts];
  const rank = new Map(preview.order.map((nodeId, index) => [nodeId, index]));
  if (rank.size !== preview.order.length || preview.order.some((nodeId) => !parts.some((part) => part.id === nodeId))) return [...parts];
  const center = (preview.order.length - 1) / 2;
  return parts.map((part) => {
    const index = rank.get(part.id);
    if (index === undefined) return part;
    const worldTransform = part.worldTransform.map((row) => [...row]);
    worldTransform[2]![3] += (index - center) * preview.gapMm;
    return { ...part, worldTransform };
  });
}
