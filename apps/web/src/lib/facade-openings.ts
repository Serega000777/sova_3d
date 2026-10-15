import type { FacadeEdit } from "@physical-ai/contracts";

export type FacadeOpeningDraft = NonNullable<FacadeEdit["openings"]>[number] & { id: string };

export function facadeSideSpanMm(
  opening: Pick<FacadeOpeningDraft, "side">,
  house: { length_mm: number; width_mm: number },
): number {
  return opening.side === "front" || opening.side === "back"
    ? house.length_mm
    : house.width_mm;
}

/** Mirror one scheduled opening around the centre line of its current facade. */
export function mirrorFacadeOpening(
  opening: FacadeOpeningDraft,
  house: { length_mm: number; width_mm: number },
): FacadeOpeningDraft | null {
  const span = facadeSideSpanMm(opening, house);
  const centre = span - opening.center_mm;
  if (
    !Number.isFinite(span)
    || !Number.isFinite(centre)
    || !Number.isFinite(opening.width_mm)
    || span < 2_000
    || opening.width_mm < 300
    || opening.width_mm > 5_000
    || centre - opening.width_mm / 2 < 0
    || centre + opening.width_mm / 2 > span
  ) {
    return null;
  }
  return { ...opening, center_mm: centre };
}

/** Duplicate keeps exact dimensions but always gets a fresh semantic surface identity. */
export function duplicateFacadeOpening(
  opening: FacadeOpeningDraft,
  newId: string,
): FacadeOpeningDraft | null {
  if (!/^[a-z0-9_-]{1,64}$/.test(newId) || newId === opening.opening_id) return null;
  return { ...opening, id: newId, opening_id: newId };
}

/** Convert a window or door to an unfilled architectural opening without moving it. */
export function convertToArchitecturalOpening(
  opening: FacadeOpeningDraft,
): FacadeOpeningDraft {
  return { ...opening, kind: "opening" };
}
