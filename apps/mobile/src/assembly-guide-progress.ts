import type { AssemblyGuideProgress } from "@physical-ai/contracts";

import type { MechanismAssemblyGuide } from "./mechanism-assembly-guide";

export type VerifiedAssemblyGuideProgress = {
  completed: Set<string>;
  revision: number;
};

/** Bind shared checklist state to the exact immutable version and rendered guide steps. */
export function verifiedAssemblyGuideProgress(
  progress: AssemblyGuideProgress,
  versionId: string,
  guide: MechanismAssemblyGuide,
): VerifiedAssemblyGuideProgress | null {
  if (
    progress.version_id !== versionId
    || progress.guide_kind !== guide.kind
    || !Number.isInteger(progress.revision)
    || progress.revision < 0
    || !Array.isArray(progress.completed_step_ids)
  ) return null;
  const allowed = new Set(guide.steps.map((step) => step.id));
  const completed = new Set<string>();
  for (const stepId of progress.completed_step_ids) {
    if (typeof stepId !== "string" || !allowed.has(stepId) || completed.has(stepId)) return null;
    completed.add(stepId);
  }
  return { completed, revision: progress.revision };
}
