export const MIN_EXPOSURE_STEP = -4;
export const MAX_EXPOSURE_STEP = 4;

export function clampExposureStep(step: number): number {
  if (!Number.isFinite(step)) return 0;
  return Math.max(MIN_EXPOSURE_STEP, Math.min(MAX_EXPOSURE_STEP, Math.round(step)));
}

/** Normalized value consumed by the patched native camera: -1…1 of its real supported range. */
export function exposureValue(step: number): number {
  return clampExposureStep(step) / MAX_EXPOSURE_STEP;
}

export function exposureLabel(step: number): string {
  const percent = Math.round(exposureValue(step) * 100);
  if (percent === 0) return "Авто · 0%";
  return `${percent > 0 ? "+" : ""}${percent}%`;
}
