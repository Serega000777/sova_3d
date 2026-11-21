import {
  BROKEN_PART_SECTIONS,
  emptyBrokenPartSectionCounts,
  type BrokenPartSectionCounts,
  type BrokenPartSectionId,
  type ScanFrame,
} from "@physical-ai/contracts";

export function landedBrokenPartCounts(frames: ScanFrame[]): BrokenPartSectionCounts {
  const counts = { ...emptyBrokenPartSectionCounts };
  for (const frame of frames) {
    const section = frame.pose?.broken_part_section;
    if (section === "whole" || section === "fracture" || section === "interior") {
      counts[section] += 1;
    }
  }
  return counts;
}

/**
 * A deterministic capture instruction, not a measured camera pose. The matching frame metadata
 * must keep `pose_source=user_confirmed_guided_step` so reconstruction and review do not mistake
 * this value for device motion, depth or calibrated position.
 */
export function guidedBrokenPartAngle(
  section: BrokenPartSectionId,
  landedInSection: number,
): number {
  const plan = BROKEN_PART_SECTIONS.find((entry) => entry.id === section);
  if (!plan) return 0;
  const step = 360 / plan.targetFrames;
  return Math.round(((landedInSection % plan.targetFrames) * step) * 1000) / 1000;
}

