import type { FacadeEdit, FacadeVariant, Job, Version } from "@physical-ai/contracts";

export type FacadeVariantCompatibility = "compatible" | "incompatible" | "server_check";

const ROOF_SURFACES: Record<FacadeEdit["roof"], string[]> = {
  none: [],
  flat: ["roof.top"],
  gable: ["roof.slope.left", "roof.slope.right"],
  shed: ["roof.slope"],
  hip: ["roof.slope.front", "roof.slope.back", "roof.slope.left", "roof.slope.right"],
};

/**
 * Return the exact semantic surface set when every opening has a stable server identity.
 * Legacy openings without opening_id stay server_check: the API owns their geometry-derived key.
 */
export function facadeRequestSurfaceKeys(request: FacadeEdit): string[] | null {
  const openings = request.openings ?? [];
  if (openings.some((opening) => !opening.opening_id?.trim())) return null;

  return [
    "wall.front",
    "wall.back",
    "wall.left",
    "wall.right",
    ...ROOF_SURFACES[request.roof],
    ...openings.flatMap((opening) => {
      const roles = opening.kind === "door"
        ? ["left", "right", "head"]
        : ["left", "right", "head", "sill"];
      return roles.map((role) => `opening.${opening.opening_id}.${role}`);
    }),
  ].sort();
}

export function facadeVariantCompatibility(
  request: FacadeEdit,
  variant: FacadeVariant,
): FacadeVariantCompatibility {
  const current = facadeRequestSurfaceKeys(request);
  if (current === null) return "server_check";
  const candidate = [...variant.surface_keys].sort();
  return current.length === candidate.length
    && current.every((surfaceKey, index) => surfaceKey === candidate[index])
    ? "compatible"
    : "incompatible";
}

/** Accept only the immutable child that the exact selected variant actually produced. */
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
