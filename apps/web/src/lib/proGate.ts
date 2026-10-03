/**
 * Account-tier UI gate (F-account-tier): which studio tools and which "detail" operation
 * kinds belong to the paid Pro toolset. Pure and render-agnostic so the decision table can
 * be unit tested without mounting the studio page. No server enforcement exists yet (the
 * payment provider isn't chosen), so this only drives what the client shows as locked.
 */
export type DetailKind = "hole" | "fillet" | "chamfer" | "shell" | "pattern" | "circle" | "mirror";

/** Whole tool-rail panels that are Pro-only; everything else stays free. */
export const PRO_LOCKED_TOOLS: readonly string[] = ["reverse", "engineer", "fit", "parts"];

/** "Detail" operation kinds that are Pro-only; "hole" is the one that stays on the Free plan. */
export const PRO_LOCKED_DETAILS: readonly DetailKind[] = [
  "fillet",
  "chamfer",
  "shell",
  "pattern",
  "circle",
  "mirror",
];

export function isProTierLockedTool(toolId: string, detail?: string): boolean {
  if (PRO_LOCKED_TOOLS.includes(toolId)) return true;
  if (toolId === "detail" && detail) return PRO_LOCKED_DETAILS.includes(detail as DetailKind);
  return false;
}
