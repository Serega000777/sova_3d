import type { Version } from "@physical-ai/contracts";

export type LocalEditPreviewSide = "before" | "after";

/** Keep viewport comparison bound to the two immutable versions in the draft decision. */
export function localEditPreviewVersion(
  side: LocalEditPreviewSide,
  before: Version | null,
  after: Version,
): Version {
  return side === "before" && before ? before : after;
}
