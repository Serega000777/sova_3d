import type { FacadeEdit } from "@physical-ai/contracts";

export type FacadeOpeningDraft = NonNullable<FacadeEdit["openings"]>[number] & { id: string };
type FacadeOpening = NonNullable<FacadeEdit["openings"]>[number];

type FacadePickVector = { x: number; y: number; z: number };
type FacadePickHouse = {
  length_mm: number;
  width_mm: number;
  floors: number;
  floor_height_mm: number;
  wall_thickness_mm: number;
};

function facadeOpeningBottomMm(opening: FacadeOpening): number {
  return opening.sill_mm ?? (opening.kind === "door" ? 0 : 900);
}

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
  house?: { floors: number; floor_height_mm: number },
): Promise<FacadeOpeningDraft[]> {
  const hydrated = await Promise.all(openings.map(async (opening) => {
    const id = opening.opening_id ?? await legacyFacadeOpeningId(opening);
    return { ...opening, opening_id: id, id };
  }));
  if (!house) return hydrated;
  return hydrated.map((opening) => {
    if (opening.floor != null) return opening;
    const absoluteBottom = facadeOpeningBottomMm(opening);
    const floor = Math.floor(absoluteBottom / house.floor_height_mm) + 1;
    const localBottom = absoluteBottom - (floor - 1) * house.floor_height_mm;
    return addressFacadeOpeningToFloor(
      { ...opening, sill_mm: localBottom },
      floor,
      house,
    ) ?? opening;
  });
}

/** Find the first scheduled opening under a model-space facade hit. */
export function findFacadeOpeningAtPoint(
  openings: readonly FacadeOpeningDraft[],
  point: FacadePickVector,
  normal: FacadePickVector,
  house: FacadePickHouse,
): string | null {
  const values = [
    point.x, point.y, point.z,
    normal.x, normal.y, normal.z,
    house.length_mm, house.width_mm, house.floor_height_mm, house.wall_thickness_mm,
  ];
  if (
    values.some((value) => !Number.isFinite(value))
    || !Number.isInteger(house.floors)
    || house.length_mm <= 0
    || house.width_mm <= 0
    || house.floor_height_mm <= 0
    || house.wall_thickness_mm <= 0
    || house.floors < 1
  ) return null;

  const normalLength = Math.hypot(normal.x, normal.y, normal.z);
  if (normalLength === 0) return null;
  if (point.z < 0 || point.z > house.floors * house.floor_height_mm) return null;

  const tolerance = Math.max(2.5, house.wall_thickness_mm * 0.08);
  const maximumWallDepth = house.wall_thickness_mm + tolerance;
  let best: { id: string; score: number } | null = null;

  for (const opening of openings) {
    const frontBack = opening.side === "front" || opening.side === "back";
    const u = frontBack ? point.x : point.y;
    const sideSpan = frontBack ? house.length_mm : house.width_mm;
    const surfaceDistance = opening.side === "front"
      ? Math.abs(point.y)
      : opening.side === "back"
        ? Math.abs(house.width_mm - point.y)
        : opening.side === "left"
          ? Math.abs(point.x)
          : Math.abs(house.length_mm - point.x);
    if (
      surfaceDistance > maximumWallDepth
      || u < 0
      || u > sideSpan
      || !Number.isFinite(opening.center_mm)
      || !Number.isFinite(opening.width_mm)
      || !Number.isFinite(opening.height_mm)
      || opening.width_mm <= 0
      || opening.height_mm <= 0
      || u < opening.center_mm - opening.width_mm / 2
      || u > opening.center_mm + opening.width_mm / 2
    ) continue;

    const sill = facadeOpeningBottomMm(opening);
    if (!Number.isFinite(sill)) continue;
    const absoluteBottom = opening.floor == null
      ? sill
      : Number.isInteger(opening.floor) && opening.floor >= 1 && opening.floor <= house.floors
        ? (opening.floor - 1) * house.floor_height_mm + sill
        : null;
    if (
      absoluteBottom == null
      || point.z < absoluteBottom
      || point.z > absoluteBottom + opening.height_mm
    ) continue;

    const outward = opening.side === "front"
      ? { x: 0, y: -1, z: 0 }
      : opening.side === "back"
        ? { x: 0, y: 1, z: 0 }
        : opening.side === "left"
          ? { x: -1, y: 0, z: 0 }
          : { x: 1, y: 0, z: 0 };
    const alignment = Math.abs(
      (normal.x * outward.x + normal.y * outward.y + normal.z * outward.z) / normalLength,
    );
    // A click can land on the opening reveal, whose normal is vertical or along the jamb.
    // Distance to the known wall plane therefore decides first; normal alignment only breaks
    // corner ties in favour of the facade the camera actually hit.
    const score = surfaceDistance + (1 - alignment) * tolerance;
    if (!best || score < best.score) best = { id: opening.id, score };
  }
  return best?.id ?? null;
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

/** Assign one exact storey; the API resolves the local sill to canonical absolute model Z. */
export function addressFacadeOpeningToFloor(
  opening: FacadeOpeningDraft,
  floor: number,
  house: { floors: number; floor_height_mm: number },
): FacadeOpeningDraft | null {
  const sill = opening.kind === "door" ? 0 : (opening.sill_mm ?? 900);
  if (
    !Number.isInteger(floor)
    || !Number.isInteger(house.floors)
    || !Number.isFinite(house.floor_height_mm)
    || floor < 1
    || floor > house.floors
    || house.floors < 1
    || house.floors > 3
    || house.floor_height_mm < 2_200
    || house.floor_height_mm > 6_000
    || !Number.isFinite(sill)
    || !Number.isFinite(opening.height_mm)
    || sill < 0
    || sill + opening.height_mm > house.floor_height_mm
  ) {
    return null;
  }
  return { ...opening, floor, sill_mm: sill };
}
