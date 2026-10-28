import type { Version, VersionComparison } from "@physical-ai/contracts";

export type LocalEditPreviewSide = "before" | "after";

/** Keep viewport comparison bound to the two immutable versions in the draft decision. */
export function localEditPreviewVersion(
  side: LocalEditPreviewSide,
  before: Version | null,
  after: Version,
): Version {
  return side === "before" && before ? before : after;
}

/** A decision card may represent a source-bound edit only while the returned version is the
 * exact draft child of that source and the canonical comparison describes the same pair. */
export function previewMatchesSource(
  version: Version,
  comparison: VersionComparison,
  sourceVersionId: string,
): boolean {
  return (
    version.state === "draft"
    && version.parent_version_id === sourceVersionId
    && comparison.awaiting_decision === true
    && comparison.before?.version_id === sourceVersionId
    && comparison.after.version_id === version.id
  );
}
