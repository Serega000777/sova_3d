export type NormalizedPhotoPoint = [number, number];

/**
 * Convert a two-point distance on one calibrated photo plane to millimetres.
 * Returns null instead of inventing a value when calibration or coordinates are invalid.
 */
export function calibratedPhotoDistanceMm(
  points: NormalizedPhotoPoint[],
  widthPx: number,
  heightPx: number,
  widthMm: number,
): number | null {
  if (
    points.length !== 2
    || ![widthPx, heightPx, widthMm].every((value) => Number.isFinite(value) && value > 0)
    || points.some((point) => point.length !== 2 || point.some((value) => !Number.isFinite(value) || value < 0 || value > 1))
  ) return null;
  const [a, b] = points;
  if (!a || !b) return null;
  return Math.hypot((b[0] - a[0]) * widthPx, (b[1] - a[1]) * heightPx) * widthMm / widthPx;
}
