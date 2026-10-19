import {
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
  const decimated = updateFreehandStroke(points, release, millimetresPerPixel);
  const bounds = pointsBounds(decimated);
  if (!bounds || decimated.length < 2) return null;
  const safeMmPerPixel = Number.isFinite(millimetresPerPixel) && millimetresPerPixel > 0
    ? millimetresPerPixel
    : 1;
  const spanMm = Math.hypot(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  return spanMm >= FREEHAND_MIN_SPAN_PX * safeMmPerPixel ? decimated : null;
}
