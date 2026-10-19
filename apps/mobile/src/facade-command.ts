type FacadeVersionLike = {
  provenance?: unknown;
} | null;

const FACADE_PARAMETER_PATTERN =
  /(?:свес|вылет\s+крыши|overhang|толщин(?:а|у|ы)\s+стен(?:ы)?|wall\s+thickness|высот(?:а|у|ы)\s+крыши|roof\s+height)/i;

export function hasExactFacade(version: FacadeVersionLike): boolean {
  const provenance = version?.provenance as
    | { facade?: { request?: unknown } }
    | null
    | undefined;
  return Boolean(provenance?.facade?.request);
}

export function isFacadeParameterCommand(prompt: string): boolean {
  return FACADE_PARAMETER_PATTERN.test(prompt.trim());
}

export function shouldProposeFacadeCommand({
  version,
  prompt,
  hasAttachments,
  hasSelection,
  hasRegion,
}: {
  version: FacadeVersionLike;
  prompt: string;
  hasAttachments: boolean;
  hasSelection: boolean;
  hasRegion: boolean;
}): boolean {
  return (
    hasExactFacade(version) &&
    isFacadeParameterCommand(prompt) &&
    !hasAttachments &&
    !hasSelection &&
    !hasRegion
  );
}
