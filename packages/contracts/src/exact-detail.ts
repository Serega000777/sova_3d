import type { Axis, EdgeSelector, FaceSelector, Vec2, Vec3 } from "./operation-plan.js";

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

export type ExactShellIssue = "invalid_thickness" | "invalid_open_face";

export interface ExactShellDraft {
  thickness: string;
  openFace: boolean;
  axis: Axis;
  sign: "+" | "-";
}

export interface ExactShellSpec {
  thickness_mm: number;
  open_face?: Extract<FaceSelector, { kind: "face_by_normal" }>;
}

export type ExactShellResult =
  | { spec: ExactShellSpec; issue: null }
  | { spec: null; issue: ExactShellIssue };

export type EdgeSelectorDraft =
  | { kind: "all_edges"; outer?: never }
  | { kind: "edges_parallel_to"; axis: Axis; outer?: boolean }
  | { kind: "edges_of_face"; axis: Axis; sign: "+" | "-"; outer?: never };

export type ExactFilletIssue = "invalid_edges" | "invalid_radius";

export interface ExactFilletDraft {
  edges: EdgeSelectorDraft;
  radius: string;
}

export interface ExactFilletSpec {
  edges: EdgeSelector;
  radius_mm: number;
}

export type ExactFilletResult =
  | { spec: ExactFilletSpec; issue: null }
  | { spec: null; issue: ExactFilletIssue };

export type ExactChamferIssue = "invalid_edges" | "invalid_distance";

export interface ExactChamferDraft {
  edges: EdgeSelectorDraft;
  distance: string;
}

export interface ExactChamferSpec {
  edges: EdgeSelector;
  distance_mm: number;
}

export type ExactChamferResult =
  | { spec: ExactChamferSpec; issue: null }
  | { spec: null; issue: ExactChamferIssue };

export type ExactLinearPatternIssue = "invalid_axis" | "invalid_count" | "invalid_spacing";

export interface ExactLinearPatternDraft {
  axis: Axis;
  count: string;
  spacing: string;
}

export interface ExactLinearPatternSpec {
  axis: Axis;
  count: number;
  spacing_mm: number;
}

export type ExactLinearPatternResult =
  | { spec: ExactLinearPatternSpec; issue: null }
  | { spec: null; issue: ExactLinearPatternIssue };

export type ExactCircularPatternIssue =
  | "invalid_axis"
  | "invalid_count"
  | "invalid_angle"
  | "invalid_origin";

export interface ExactCircularPatternDraft {
  axis: Axis;
  count: string;
  angle: string;
  originX: string;
  originY: string;
  originZ: string;
}

export interface ExactCircularPatternSpec {
  axis: Axis;
  count: number;
  angle_deg: number;
  origin_mm: Vec3;
}

export type ExactCircularPatternResult =
  | { spec: ExactCircularPatternSpec; issue: null }
  | { spec: null; issue: ExactCircularPatternIssue };

export type ExactMirrorIssue = "invalid_axis" | "invalid_offset" | "invalid_keep_original";

export interface ExactMirrorDraft {
  axis: Axis;
  offset: string;
  keepOriginal: boolean;
}

export interface ExactMirrorSpec {
  axis: Axis;
  offset_mm: number;
  keep_original: boolean;
}

export type ExactMirrorResult =
  | { spec: ExactMirrorSpec; issue: null }
  | { spec: null; issue: ExactMirrorIssue };

function finiteDecimal(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function isAxis(value: unknown): value is Axis {
  return value === "x" || value === "y" || value === "z";
}

function edgeSelectorSpec(draft: EdgeSelectorDraft): EdgeSelector | null {
  if (draft.kind === "all_edges") {
    return "outer" in draft ? null : { kind: "all_edges" };
  }
  if (draft.kind === "edges_parallel_to") {
    if (!isAxis(draft.axis) || (draft.outer !== undefined && typeof draft.outer !== "boolean")) {
      return null;
    }
    return draft.outer === undefined
      ? { kind: "edges_parallel_to", axis: draft.axis }
      : { kind: "edges_parallel_to", axis: draft.axis, outer: draft.outer };
  }
  if (
    draft.kind === "edges_of_face"
    && isAxis(draft.axis)
    && (draft.sign === "+" || draft.sign === "-")
    && !("outer" in draft)
  ) {
    return {
      kind: "edges_of_face",
      face: { kind: "face_by_normal", axis: draft.axis, sign: draft.sign },
    };
  }
  return null;
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
 * A closed shell ignores stale face controls. An open shell accepts only the same
 * symbolic axis/sign face selector that the server and web Studio use.
 */
export function shellSpec(draft: ExactShellDraft): ExactShellResult {
  const thickness = finiteDecimal(draft.thickness);
  if (thickness === null || thickness <= 0 || thickness > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_thickness" };
  }

  if (typeof draft.openFace !== "boolean") {
    return { spec: null, issue: "invalid_open_face" };
  }
  if (!draft.openFace) return { spec: { thickness_mm: thickness }, issue: null };
  if (!isAxis(draft.axis) || (draft.sign !== "+" && draft.sign !== "-")) {
    return { spec: null, issue: "invalid_open_face" };
  }

  return {
    spec: {
      thickness_mm: thickness,
      open_face: { kind: "face_by_normal", axis: draft.axis, sign: draft.sign },
    },
    issue: null,
  };
}

/** Parse a symbolic edge selector and radius into a server-valid fillet spec. */
export function filletSpec(draft: ExactFilletDraft): ExactFilletResult {
  const edges = edgeSelectorSpec(draft.edges);
  if (!edges) return { spec: null, issue: "invalid_edges" };

  const radius = finiteDecimal(draft.radius);
  if (radius === null || radius <= 0 || radius > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_radius" };
  }

  return { spec: { edges, radius_mm: radius }, issue: null };
}

/** Parse a symbolic edge selector and distance into a server-valid chamfer spec. */
export function chamferSpec(draft: ExactChamferDraft): ExactChamferResult {
  const edges = edgeSelectorSpec(draft.edges);
  if (!edges) return { spec: null, issue: "invalid_edges" };

  const distance = finiteDecimal(draft.distance);
  if (distance === null || distance <= 0 || distance > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_distance" };
  }

  return { spec: { edges, distance_mm: distance }, issue: null };
}

/** Parse a linear body pattern using the same strict bounds as the API model. */
export function linearPatternSpec(draft: ExactLinearPatternDraft): ExactLinearPatternResult {
  if (!isAxis(draft.axis)) return { spec: null, issue: "invalid_axis" };

  const count = finiteDecimal(draft.count);
  if (count === null || !Number.isInteger(count) || count < 2 || count > 100) {
    return { spec: null, issue: "invalid_count" };
  }

  const spacing = finiteDecimal(draft.spacing);
  if (spacing === null || spacing <= 0 || spacing > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_spacing" };
  }

  return {
    spec: { axis: draft.axis, count, spacing_mm: spacing },
    issue: null,
  };
}

/** Parse a circular body pattern using the same strict bounds as the API model. */
export function circularPatternSpec(
  draft: ExactCircularPatternDraft,
): ExactCircularPatternResult {
  if (!isAxis(draft.axis)) return { spec: null, issue: "invalid_axis" };

  const count = finiteDecimal(draft.count);
  if (count === null || !Number.isInteger(count) || count < 2 || count > 100) {
    return { spec: null, issue: "invalid_count" };
  }

  const angle = finiteDecimal(draft.angle);
  if (angle === null || angle <= 0 || angle > 360) {
    return { spec: null, issue: "invalid_angle" };
  }

  const originX = finiteDecimal(draft.originX);
  const originY = finiteDecimal(draft.originY);
  const originZ = finiteDecimal(draft.originZ);
  if (originX === null || originY === null || originZ === null) {
    return { spec: null, issue: "invalid_origin" };
  }

  return {
    spec: {
      axis: draft.axis,
      count,
      angle_deg: angle,
      origin_mm: [originX, originY, originZ],
    },
    issue: null,
  };
}

/** Parse an axis-aligned mirror plane using the same strict bounds as the API model. */
export function mirrorSpec(draft: ExactMirrorDraft): ExactMirrorResult {
  if (!isAxis(draft.axis)) return { spec: null, issue: "invalid_axis" };

  const offset = finiteDecimal(draft.offset);
  if (offset === null || offset < -MAX_EXACT_DETAIL_MM || offset > MAX_EXACT_DETAIL_MM) {
    return { spec: null, issue: "invalid_offset" };
  }
  if (typeof draft.keepOriginal !== "boolean") {
    return { spec: null, issue: "invalid_keep_original" };
  }

  return {
    spec: { axis: draft.axis, offset_mm: offset, keep_original: draft.keepOriginal },
    issue: null,
  };
}
