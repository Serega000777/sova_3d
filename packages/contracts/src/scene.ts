import type { Point } from "./floor-plan.js";

/** A furniture-style node's declared size, projected onto the plan's ground plane. */
export interface PlanFootprint {
  nodeId: string;
  label: string;
  at: Point;
  rotationDeg: number;
  widthMm: number;
  depthMm: number;
}

/**
 * Project one resolved scene node's world transform onto the plan XY ground plane as a
 * rotated rectangle, using the width/depth the node's placement job declared (`footprint_mm`)
 * rather than an inferred mesh bounding box, so a later rename/reparent in the scene tree never
 * loses or misreads the footprint. Returns null for nodes with no declared footprint, a hidden
 * effective visibility, or a non-object kind (groups cannot own geometry).
 */
export function planFootprintFromNode(node: {
  id: string;
  name: string;
  kind: string;
  footprint_mm?: readonly number[] | null;
  world_transform: readonly (readonly number[])[];
  effective_visible: boolean;
}): PlanFootprint | null {
  if (!node.effective_visible || node.kind !== "object") return null;
  const footprint = node.footprint_mm;
  if (!footprint || footprint.length !== 2) return null;
  const [widthMm, depthMm] = footprint as [number, number];
  if (!Number.isFinite(widthMm) || !Number.isFinite(depthMm) || widthMm <= 0 || depthMm <= 0) {
    return null;
  }
  const m = node.world_transform;
  if (m.length !== 4 || m.some((row) => row.length !== 4)) return null;
  const rotationDeg = (Math.atan2(m[1]![0]!, m[0]![0]!) * 180) / Math.PI;
  const at: Point = [m[0]![3]!, m[1]![3]!];
  return { nodeId: node.id, label: node.name, at, rotationDeg, widthMm, depthMm };
}

/** Fail-closed validation for a server-resolved scene transform before a renderer uses it. */
export function sceneTransformValues(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 4) {
    throw new Error("invalid scene transform");
  }
  const rows = value.map((row) => {
    if (
      !Array.isArray(row) ||
      row.length !== 4 ||
      row.some(
        (item) => typeof item !== "number" || !Number.isFinite(item) || Math.abs(item) > 1_000_000,
      )
    ) {
      throw new Error("invalid scene transform");
    }
    return row;
  });
  const [a, b, c] = rows[0]!;
  const [d, e, f] = rows[1]!;
  const [g, h, i] = rows[2]!;
  const determinant =
    a! * (e! * i! - f! * h!) -
    b! * (d! * i! - f! * g!) +
    c! * (d! * h! - e! * g!);
  const affine = rows[3]!.every(
    (item, index) => Math.abs(item - ([0, 0, 0, 1][index] as number)) <= 1e-9,
  );
  if (!affine || Math.abs(determinant) < 1e-12) {
    throw new Error("invalid scene transform");
  }
  return rows.flat();
}
