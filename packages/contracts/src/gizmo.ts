/** Pure screen-drag math shared by transform gizmos and their deterministic tests. */

export function linearGizmoValue(
  startMagnitude: number,
  scalarPixels: number,
  pixelsPerMagnitude: number,
  min = Number.NEGATIVE_INFINITY,
  max = Number.POSITIVE_INFINITY,
): number {
  if (
    !Number.isFinite(startMagnitude) ||
    !Number.isFinite(scalarPixels) ||
    !Number.isFinite(pixelsPerMagnitude) ||
    pixelsPerMagnitude <= 0
  ) {
    return Math.min(max, Math.max(min, Number.isFinite(startMagnitude) ? startMagnitude : 0));
  }
  return Math.min(max, Math.max(min, startMagnitude + scalarPixels / pixelsPerMagnitude));
}

export function rotationGizmoValue(
  startMagnitude: number,
  startPointerAngleRad: number,
  pointerAngleRad: number,
): number {
  if (
    !Number.isFinite(startMagnitude) ||
    !Number.isFinite(startPointerAngleRad) ||
    !Number.isFinite(pointerAngleRad)
  ) {
    return Number.isFinite(startMagnitude) ? startMagnitude : 0;
  }
  let delta = ((pointerAngleRad - startPointerAngleRad) * 180) / Math.PI;
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  return Math.min(359, Math.max(-359, startMagnitude + delta));
}
