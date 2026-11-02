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
  envelope_overlaps: EnvelopeOverlap[];
  mesh_collisions: MeshCollision[];
  collision_unavailable_pairs: CollisionUnavailable[];
  collision_status: "checked" | "unavailable";
};

const finiteVector3 = (value: unknown): value is [number, number, number] => (
  Array.isArray(value)
  && value.length === 3
  && value.every((item) => typeof item === "number" && Number.isFinite(item))
);

const nodePair = (value: unknown): value is { node_a_id: string; node_b_id: string } => {
  if (!value || typeof value !== "object") return false;
  const pair = value as { node_a_id?: unknown; node_b_id?: unknown };
  return typeof pair.node_a_id === "string"
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

export function parseGeometryInspection(
  value: unknown,
  expectedNodeIds?: readonly string[],
): GeometryInspection | null {
  if (!value || typeof value !== "object") return null;
  const result = value as Record<string, unknown>;
  if (result.ok !== true || !Number.isInteger(result.component_count) || Number(result.component_count) < 1) {
    return null;
  }
  const expectedNodes = expectedNodeIds ? new Set(expectedNodeIds) : null;
  if (expectedNodes && (
    expectedNodes.size !== expectedNodeIds!.length
    || expectedNodes.size !== Number(result.component_count)
  )) return null;
  const sceneMin = result.scene_bbox_min_mm;
  const sceneMax = result.scene_bbox_max_mm;
  if (!finiteVector3(sceneMin) || !finiteVector3(sceneMax)) {
    return null;
  }
  if (sceneMin.some((minimum, index) => minimum > sceneMax[index]!)) {
    return null;
  }
  if (!Array.isArray(result.envelope_overlaps)
    || !Array.isArray(result.mesh_collisions)
    || !Array.isArray(result.collision_unavailable_pairs)) {
    return null;
  }
  const envelopes: EnvelopeOverlap[] = [];
  const envelopeKeys = new Set<string>();
  for (const raw of result.envelope_overlaps) {
    if (!nodePair(raw)) return null;
    if (expectedNodes && (!expectedNodes.has(raw.node_a_id) || !expectedNodes.has(raw.node_b_id))) {
      return null;
    }
    const overlap = raw as typeof raw & { overlap_mm?: unknown };
    if (!finiteVector3(overlap.overlap_mm) || overlap.overlap_mm.some((item) => item <= 0)) {
      return null;
    }
    const key = pairKey(raw);
    if (envelopeKeys.has(key)) return null;
    envelopeKeys.add(key);
    envelopes.push({ ...raw, overlap_mm: overlap.overlap_mm });
  }
  const collisions: MeshCollision[] = [];
  const collisionKeys = new Set<string>();
  for (const raw of result.mesh_collisions) {
    if (!nodePair(raw)) return null;
    const collision = raw as typeof raw & {
      interference_mm3?: unknown;
      bbox_min_mm?: unknown;
      bbox_max_mm?: unknown;
    };
    const bboxMin = collision.bbox_min_mm;
    const bboxMax = collision.bbox_max_mm;
    if (typeof collision.interference_mm3 !== "number"
      || !Number.isFinite(collision.interference_mm3)
      || collision.interference_mm3 <= 0
      || !finiteVector3(bboxMin)
      || !finiteVector3(bboxMax)
      || bboxMin.some((minimum, index) => minimum >= bboxMax[index]!)) {
      return null;
    }
    const key = pairKey(raw);
    if (!envelopeKeys.has(key) || collisionKeys.has(key)) return null;
    collisionKeys.add(key);
    collisions.push({
      ...raw,
      interference_mm3: collision.interference_mm3,
      bbox_min_mm: bboxMin,
      bbox_max_mm: bboxMax,
    });
  }
  const unavailable: CollisionUnavailable[] = [];
  const unavailableKeys = new Set<string>();
  for (const raw of result.collision_unavailable_pairs) {
    if (!nodePair(raw)) return null;
    const item = raw as typeof raw & { reason?: unknown };
    if (!(["non_watertight", "boolean_failed", "candidate_limit"] as const).includes(
      item.reason as "non_watertight" | "boolean_failed" | "candidate_limit",
    )) return null;
    const key = pairKey(raw);
    if (!envelopeKeys.has(key) || collisionKeys.has(key) || unavailableKeys.has(key)) return null;
    unavailableKeys.add(key);
    unavailable.push({ ...raw, reason: item.reason as CollisionUnavailable["reason"] });
  }
  if ((result.collision_status === "checked" && unavailable.length !== 0)
    || (result.collision_status === "unavailable" && unavailable.length === 0)) {
    return null;
  }
  if (result.collision_status !== "checked" && result.collision_status !== "unavailable") {
    return null;
  }
  return {
    ok: true,
    component_count: Number(result.component_count),
    scene_bbox_min_mm: sceneMin,
    scene_bbox_max_mm: sceneMax,
    envelope_overlaps: envelopes,
    mesh_collisions: collisions,
    collision_unavailable_pairs: unavailable,
    collision_status: result.collision_status,
  };
}
