import type { Axis, FaceSelector, Vec2 } from "./operation-plan.js";

export type ExactHoleIssue =
  | "invalid_position"
  | "invalid_diameter"
  | "invalid_depth";

/** Mirrors the API OperationPlan `Positive` upper bound for exact detail dimensions. */
export const MAX_EXACT_DETAIL_MM = 10_000;

export interface ExactHoleDraft {
  axis: Axis;
  sign: "+" | "-";
  positionU: string;
  positionV: string;
  diameter: string;
  through: boolean;
  depth: string;
}

export interface ExactHoleSpec {
  face: Extract<FaceSelector, { kind: "face_by_normal" }>;
  position_mm: Vec2;
  diameter_mm: number;
  depth_mm: number | null;
}

export type ExactHoleResult =
  | { spec: ExactHoleSpec; issue: null }
  | { spec: null; issue: ExactHoleIssue };

export type ExactShellIssue = "invalid_thickness";

export interface ExactShellDraft {
  thickness: string;
}

export interface ExactShellSpec {
  thickness_mm: number;
}

export type ExactShellResult =
  | { spec: ExactShellSpec; issue: null }
  | { spec: null; issue: ExactShellIssue };

function finiteDecimal(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Parse the mobile exact-hole inspector into canonical millimetres.
 *
 * The helper intentionally returns no partial operation: malformed coordinates,
 * non-positive dimensions, NaN and infinities all fail closed before a job is queued.
 */
export function exactHoleSpec(draft: ExactHoleDraft): ExactHoleResult {
  const u = finiteDecimal(draft.positionU);
  const v = finiteDecimal(draft.positionV);
  if (u === null || v === null) return { spec: null, issue: "invalid_position" };

  const diameter = finiteDecimal(draft.diameter);
  if (diameter === null || diameter <= 0 || diameter > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_diameter" };
  }

  let depth: number | null = null;
  if (!draft.through) {
    depth = finiteDecimal(draft.depth);
    if (depth === null || depth <= 0 || depth > MAX_EXACT_DETAIL_MM) {
      return { spec: null, issue: "invalid_depth" };
    }
  }

  return {
    spec: {
      face: { kind: "face_by_normal", axis: draft.axis, sign: draft.sign },
      position_mm: [u, v],
      diameter_mm: diameter,
      depth_mm: depth,
    },
    issue: null,
  };
}

/**
 * Parse the mobile exact-shell inspector into canonical millimetres.
 *
 * V1 intentionally creates a closed hollow shell. Selecting an `open_face`
 * remains outside this helper until mobile can address a face explicitly.
 */
export function shellSpec(draft: ExactShellDraft): ExactShellResult {
  const thickness = finiteDecimal(draft.thickness);
  if (thickness === null || thickness <= 0 || thickness > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_thickness" };
  }

  return { spec: { thickness_mm: thickness }, issue: null };
}
