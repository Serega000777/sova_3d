import type { SketchSegment, Vec2 } from "@physical-ai/contracts";

export type MobileSketchSegmentKind = SketchSegment["kind"];

export type CurveDraft = {
  kind: MobileSketchSegmentKind;
  start: Vec2;
  end: Vec2;
  arcCenter?: Vec2;
  arcClockwise?: boolean;
  splinePointsText?: string;
  nurbsControlPointsText?: string;
  nurbsDegree?: number;
  nurbsWeightsText?: string;
  nurbsKnotsText?: string;
  nurbsMultiplicitiesText?: string;
};

export type CurveDraftResult =
  | { segment: SketchSegment; issue: null }
  | { segment: null; issue: "arc" | "spline" | "nurbs" };

const TOLERANCE_MM = 1e-5;

function numberList(value: string): number[] {
  return value.split(/[,;\s]+/).filter(Boolean).map(Number);
}

function pointRows(value: string): Vec2[] | null {
  const rows = value
    .split(/\n+/)
    .filter((row) => row.trim())
    .map(numberList);
  if (rows.some((point) => point.length !== 2 || point.some((coordinate) => !Number.isFinite(coordinate)))) {
    return null;
  }
  return rows as Vec2[];
}

function consecutivePointsAreDistinct(points: Vec2[]): boolean {
  return points.slice(1).every((point, index) =>
    Math.hypot(point[0] - points[index][0], point[1] - points[index][1]) > TOLERANCE_MM,
  );
}

export function buildMobileSketchSegment(draft: CurveDraft): CurveDraftResult {
  if (draft.kind === "line") return { segment: { kind: "line" }, issue: null };

  if (draft.kind === "arc") {
    const center = draft.arcCenter;
    if (!center || center.some((value) => !Number.isFinite(value))) {
      return { segment: null, issue: "arc" };
    }
    const startRadius = Math.hypot(draft.start[0] - center[0], draft.start[1] - center[1]);
    const endRadius = Math.hypot(draft.end[0] - center[0], draft.end[1] - center[1]);
    if (Math.min(startRadius, endRadius) <= TOLERANCE_MM || Math.abs(startRadius - endRadius) > TOLERANCE_MM) {
      return { segment: null, issue: "arc" };
    }
    return {
      segment: { kind: "arc", center_mm: center, clockwise: draft.arcClockwise ?? false },
      issue: null,
    };
  }

  if (draft.kind === "spline") {
    const throughPoints = pointRows(draft.splinePointsText ?? "");
    const chain = throughPoints ? [draft.start, ...throughPoints, draft.end] : [];
    if (!throughPoints || throughPoints.length < 1 || throughPoints.length > 30 || !consecutivePointsAreDistinct(chain)) {
      return { segment: null, issue: "spline" };
    }
    return { segment: { kind: "spline", through_points_mm: throughPoints }, issue: null };
  }

  const controls = pointRows(draft.nurbsControlPointsText ?? "");
  const degree = draft.nurbsDegree ?? Number.NaN;
  const weights = numberList(draft.nurbsWeightsText ?? "");
  const knots = numberList(draft.nurbsKnotsText ?? "");
  const multiplicities = numberList(draft.nurbsMultiplicitiesText ?? "");
  const poleCount = (controls?.length ?? 0) + 2;
  const valid = controls !== null
    && controls.length >= 1 && controls.length <= 30
    && consecutivePointsAreDistinct([draft.start, ...controls, draft.end])
    && Number.isInteger(degree) && degree >= 1 && degree <= 5 && degree < poleCount
    && weights.length === poleCount
    && weights.every((value) => Number.isFinite(value) && value > 0 && value <= 1_000_000)
    && knots.length >= 2 && knots.length <= 32 && knots.length === multiplicities.length
    && knots.every((value) => Number.isFinite(value) && Math.abs(value) <= 1_000_000)
    && knots.slice(1).every((value, index) => knots[index] < value)
    && multiplicities.every((value) => Number.isInteger(value) && value >= 1 && value <= 6)
    && multiplicities[0] === degree + 1
    && multiplicities.at(-1) === degree + 1
    && multiplicities.slice(1, -1).every((value) => value <= degree)
    && multiplicities.reduce((sum, value) => sum + value, 0) === poleCount + degree + 1;
  if (!valid) return { segment: null, issue: "nurbs" };
  return {
    segment: {
      kind: "nurbs",
      control_points_mm: controls,
      degree,
      weights,
      knots,
      multiplicities,
    },
    issue: null,
  };
}

export function scaleMobileSketchSegment(segment: SketchSegment, scale: number): SketchSegment {
  if (segment.kind === "arc") {
    return { ...segment, center_mm: [segment.center_mm[0] * scale, segment.center_mm[1] * scale] };
  }
  if (segment.kind === "spline") {
    return {
      ...segment,
      through_points_mm: segment.through_points_mm.map(([x, y]) => [x * scale, y * scale]),
    };
  }
  if (segment.kind === "nurbs") {
    return {
      ...segment,
      control_points_mm: segment.control_points_mm.map(([x, y]) => [x * scale, y * scale]),
    };
  }
  return segment;
}
