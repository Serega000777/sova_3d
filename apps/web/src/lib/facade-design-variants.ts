import type { FacadeVariant, Job, Version } from "@physical-ai/contracts";

/** Accept only the immutable child that the exact selected variant actually produced.
 *  Mirrors mobile's `verifiedAppliedFacadeVariant` (apps/mobile/src/facade-design-variants.ts). */
export function verifiedAppliedFacadeVariant(
  job: Job,
  version: Version,
  sourceVersionId: string,
  variant: FacadeVariant,
): boolean {
  const result = job.result as { version_id?: unknown } | null;
  const facade = (version.provenance as {
    facade?: { applied_variant?: { name?: unknown; version_id?: unknown } };
  } | undefined)?.facade;
  return job.status === "succeeded"
    && result?.version_id === version.id
    && version.parent_version_id === sourceVersionId
    && facade?.applied_variant?.version_id === variant.version_id
    && facade.applied_variant.name === variant.name;
}
