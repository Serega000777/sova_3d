export const BLUR_SHARPNESS_THRESHOLD = 0.35;

export type ScanFrameWarningCode = "blurry" | "motion";

export interface ScanFrameQualityLike {
  sequence_no: number;
  kind?: string;
  quality: unknown;
}

export interface ScanFrameWarning {
  sequenceNo: number;
  codes: ScanFrameWarningCode[];
}

/**
 * Turn only persisted, measured per-frame signals into local warnings.
 * Unknown or malformed client quality fields are ignored rather than invented.
 */
export function scanFrameWarnings(frames: readonly ScanFrameQualityLike[]): ScanFrameWarning[] {
  const warnings: ScanFrameWarning[] = [];
  for (const frame of frames) {
    if (frame.kind && frame.kind !== "rgb") continue;
    if (!Number.isInteger(frame.sequence_no) || frame.sequence_no < 0) continue;
    if (!frame.quality || typeof frame.quality !== "object" || Array.isArray(frame.quality)) continue;
    const quality = frame.quality as Record<string, unknown>;
    const codes: ScanFrameWarningCode[] = [];
    const sharpness = quality.sharpness;
    if (
      typeof sharpness === "number" &&
      Number.isFinite(sharpness) &&
      sharpness >= 0 &&
      sharpness <= 1 &&
      sharpness < BLUR_SHARPNESS_THRESHOLD
    ) {
      codes.push("blurry");
    }
    if (quality.steady === false) codes.push("motion");
    if (codes.length > 0) warnings.push({ sequenceNo: frame.sequence_no, codes });
  }
  return warnings.sort((left, right) => left.sequenceNo - right.sequenceNo);
}
