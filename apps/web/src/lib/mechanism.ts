/** Row-major platform-mm transform for the bounded hinged-lid kinematic preview. */
export function hingedLidTransform(angleDeg: number, pivotZMm: number): number[][] {
  const safeAngle = Number.isFinite(angleDeg) ? Math.max(0, Math.min(180, angleDeg)) : 0;
  const safePivot = Number.isFinite(pivotZMm) ? pivotZMm : 0;
  const angle = safeAngle * Math.PI / 180;
  const rawCosine = Math.cos(angle);
  const rawSine = Math.sin(angle);
  const cosine = Math.abs(rawCosine) < 1e-12 ? 0 : rawCosine;
  const sine = Math.abs(rawSine) < 1e-12 ? 0 : rawSine;
  const negativeSine = sine === 0 ? 0 : -sine;
  return [
    [1, 0, 0, 0],
    [0, cosine, negativeSine, 0],
    [0, sine, cosine, safePivot],
    [0, 0, 0, 1],
  ];
}

/**
 * Row-major platform-mm transform for the bounded sliding-lid preview: the lid's own world
 * matrix times a local +Y travel. The GLB export keys exactly this as glTF translation.
 */
export function slidingLidTransform(
  worldTransform: number[][],
  travelMm: number,
  minTravelMm: number,
  maxTravelMm: number,
): number[][] {
  const low = Number.isFinite(minTravelMm) ? minTravelMm : 0;
  const high = Number.isFinite(maxTravelMm) && maxTravelMm > low ? maxTravelMm : low;
  const travel = Number.isFinite(travelMm) ? Math.max(low, Math.min(high, travelMm)) : low;
  return worldTransform.map((row) => {
    const moved = row.slice();
    moved[3] = (row[3] ?? 0) + (row[1] ?? 0) * travel;
    return moved;
  });
}

type JointRecord = {
  type?: unknown;
  node_id?: unknown;
  axis?: unknown;
  pivot_mm?: unknown;
  min_angle_deg?: unknown;
  max_angle_deg?: unknown;
  min_travel_mm?: unknown;
  max_travel_mm?: unknown;
};
type MechanismRecord = { kind?: unknown; joint?: JointRecord; validation?: { note?: unknown } };

export type SceneMechanism =
  | { kind: "hinged_lid"; nodeId: string; pivotZMm: number; maxAngleDeg: number }
  | { kind: "sliding_lid"; nodeId: string; minTravelMm: number; maxTravelMm: number };

/** A bounded value for the two-second one-joint Studio playback. */
export function mechanismPlaybackValue(min: number, max: number, progress: number): number {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return min;
  const bounded = Number.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : 0;
  return min + (max - min) * bounded;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The single trusted joint a scene version animates — the same rule the GLB export applies:
 * a malformed record, a hidden lid, or a scene carrying both a hinge and a slide animates nothing.
 */
export function sceneMechanism(
  provenance: Record<string, unknown> | null | undefined,
  visibleNodeIds: ReadonlySet<string>,
): SceneMechanism | null {
  const hinge = provenance?.build_hinged_lid as MechanismRecord | undefined;
  const slide = provenance?.build_sliding_lid as MechanismRecord | undefined;
  if ((hinge === undefined) === (slide === undefined)) return null;
  const record = (hinge ?? slide)!;
  const joint = record?.joint;
  if (!joint || typeof joint !== "object") return null;
  const nodeId = joint.node_id;
  if (typeof nodeId !== "string" || !visibleNodeIds.has(nodeId)) return null;
  if (!["x", "y", "z"].includes(joint.axis as string)) return null;
  if (hinge !== undefined) {
    const low = finite(joint.min_angle_deg ?? 0);
    const high = finite(joint.max_angle_deg ?? 0);
    if (record.kind !== "hinged_lid" || joint.type !== "revolute" || joint.axis !== "x" || low === null || high === null || high <= low) return null;
    const pivot = Array.isArray(joint.pivot_mm) ? finite(joint.pivot_mm[2]) : null;
    return { kind: "hinged_lid", nodeId, pivotZMm: pivot ?? 0, maxAngleDeg: high };
  }
  const low = finite(joint.min_travel_mm ?? 0);
  const high = finite(joint.max_travel_mm ?? 0);
  if (record.kind !== "sliding_lid" || joint.type !== "prismatic" || joint.axis !== "y" || low === null || high === null || high <= low) return null;
  return { kind: "sliding_lid", nodeId, minTravelMm: low, maxTravelMm: high };
}
