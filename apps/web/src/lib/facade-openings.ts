import type { FacadeEdit } from "@physical-ai/contracts";

export type FacadeOpeningDraft = NonNullable<FacadeEdit["openings"]>[number] & { id: string };
type FacadeOpening = NonNullable<FacadeEdit["openings"]>[number];

/** Match CPython's finite binary64 float.hex(), which the API uses for legacy identities. */
function pythonFloatHex(value: number): string {
  if (!Number.isFinite(value)) throw new Error("facade opening dimensions must be finite");
  if (value === 0) return Object.is(value, -0) ? "-0x0.0p+0" : "0x0.0p+0";

  const sign = value < 0 ? "-" : "";
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Math.abs(value));
  const high = view.getUint32(0);
  const low = view.getUint32(4);
  const exponentBits = (high >>> 20) & 0x7ff;
  const fraction = ((BigInt(high & 0xfffff) << 32n) | BigInt(low))
    .toString(16)
    .padStart(13, "0");
  if (exponentBits === 0) return `${sign}0x0.${fraction}p-1022`;
  const exponent = exponentBits - 1023;
  return `${sign}0x1.${fraction}p${exponent >= 0 ? "+" : ""}${exponent}`;
}

/** Reproduce services/api opening_key() so legacy material surface keys remain addressable. */
export async function legacyFacadeOpeningId(opening: FacadeOpening): Promise<string> {
  const identity = [
    opening.kind,
    opening.side,
    pythonFloatHex(opening.center_mm),
    pythonFloatHex(opening.width_mm),
    pythonFloatHex(opening.height_mm),
    pythonFloatHex(opening.sill_mm ?? (opening.kind === "door" ? 0 : 900)),
  ].join("|");
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(identity) as unknown as ArrayBuffer,
  );
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `legacy-${hex.slice(0, 16)}`;
}

/** Hydrate editor-only ids without changing the API's stable semantic opening identity. */
export async function hydrateFacadeOpenings(
  openings: FacadeOpening[],
): Promise<FacadeOpeningDraft[]> {
  return Promise.all(openings.map(async (opening) => {
    const id = opening.opening_id ?? await legacyFacadeOpeningId(opening);
    return { ...opening, opening_id: id, id };
  }));
}

export function facadeOpeningSurfaceKeys(opening: FacadeOpeningDraft): string[] {
  const roles = opening.kind !== "door" ? ["left", "right", "head", "sill"] : ["left", "right", "head"];
  const identity = opening.opening_id ?? opening.id;
  return roles.map((role) => `opening.${identity}.${role}`);
}

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
