import {
  type Annotation,
  type AnnotationBase,
  type Point,
  decimateFreehandPoints,
  pointsBounds,
} from "@physical-ai/contracts";

export const FREEHAND_SAMPLE_DISTANCE_PX = 2;
export const FREEHAND_MIN_SPAN_PX = 8;

/** Keep the live draft light enough to render smoothly while retaining its current endpoint. */
export function updateFreehandStroke(
  points: readonly Point[],
  next: Point,
  millimetresPerPixel: number,
): Point[] {
  return decimateFreehandPoints(
    [...points, next],
    millimetresPerPixel,
    FREEHAND_SAMPLE_DISTANCE_PX,
  );
}

/** Return a server-safe completed stroke, or null for taps/jitter and malformed coordinates. */
export function finishFreehandStroke(
  points: readonly Point[],
  release: Point,
  millimetresPerPixel: number,
): Point[] | null {
  if (!Number.isFinite(millimetresPerPixel) || millimetresPerPixel <= 0) return null;
  const decimated = updateFreehandStroke(points, release, millimetresPerPixel);
  const bounds = pointsBounds(decimated);
  if (!bounds || decimated.length < 2) return null;
  const [first] = decimated;
  if (!first || !decimated.some((point) => point[0] !== first[0] || point[1] !== first[1])) return null;
  const spanMm = Math.hypot(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  return spanMm >= FREEHAND_MIN_SPAN_PX * millimetresPerPixel ? decimated : null;
}

export interface FreehandCommit {
  annotation: Extract<Annotation, { kind: "freehand" }>;
  annotations: Annotation[];
}

/** Build exactly one immutable history value when a release completes a valid stroke. */
export function commitFreehandStroke(
  annotations: readonly Annotation[],
  base: AnnotationBase,
  points: readonly Point[],
  release: Point,
  millimetresPerPixel: number,
): FreehandCommit | null {
  const completed = finishFreehandStroke(points, release, millimetresPerPixel);
  if (!completed) return null;
  const annotation: Extract<Annotation, { kind: "freehand" }> = {
    ...base,
    kind: "freehand",
    points: completed,
  };
  return { annotation, annotations: [...annotations, annotation] };
}
