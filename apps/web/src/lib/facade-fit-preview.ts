import type { FacadeCompatibility } from "@physical-ai/contracts";

export type FacadeSide = "front" | "back" | "left" | "right";

export type FacadePreviewOpening = FacadeCompatibility["openings"][number] & {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type FacadePreviewGeometry = {
  width: number;
  height: number;
  wall: { x: number; y: number; width: number; height: number };
  floorLines: number[];
  openings: FacadePreviewOpening[];
};

const VIEW_WIDTH = 720;
const VIEW_HEIGHT = 360;
const PADDING_X = 36;
const PADDING_Y = 28;

export function facadeSpanMm(
  compatibility: FacadeCompatibility,
  side: FacadeSide,
): number | null {
  const value = side === "front" || side === "back"
    ? compatibility.facade_length_mm
    : compatibility.facade_width_mm;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export function facadePreviewGeometry(
  compatibility: FacadeCompatibility,
  side: FacadeSide,
): FacadePreviewGeometry | null {
  const spanMm = facadeSpanMm(compatibility, side);
  const floorHeightMm = compatibility.floor_height_mm;
  const floors = compatibility.floors;
  if (
    spanMm === null
    || typeof floorHeightMm !== "number"
    || !Number.isFinite(floorHeightMm)
    || floorHeightMm <= 0
    || typeof floors !== "number"
    || !Number.isInteger(floors)
    || floors <= 0
  ) return null;

  const totalHeightMm = floorHeightMm * floors;
  const wall = {
    x: PADDING_X,
    y: PADDING_Y,
    width: VIEW_WIDTH - PADDING_X * 2,
    height: VIEW_HEIGHT - PADDING_Y * 2,
  };
  const openings = compatibility.openings
    .filter((opening) => opening.side === side)
    .filter((opening) => [
      opening.center_mm,
      opening.width_mm,
      opening.height_mm,
      opening.bottom_mm,
    ].every((value) => Number.isFinite(value)))
    .filter((opening) => (
      opening.width_mm > 0
      && opening.height_mm > 0
      && opening.bottom_mm >= 0
      && opening.center_mm - opening.width_mm / 2 >= 0
      && opening.center_mm + opening.width_mm / 2 <= spanMm
      && opening.bottom_mm + opening.height_mm <= totalHeightMm
    ))
    .map((opening) => ({
      ...opening,
      x: wall.x + ((opening.center_mm - opening.width_mm / 2) / spanMm) * wall.width,
      y: wall.y + ((totalHeightMm - opening.bottom_mm - opening.height_mm) / totalHeightMm) * wall.height,
      width: (opening.width_mm / spanMm) * wall.width,
      height: (opening.height_mm / totalHeightMm) * wall.height,
    }));
  return {
    width: VIEW_WIDTH,
    height: VIEW_HEIGHT,
    wall,
    floorLines: Array.from({ length: floors - 1 }, (_, index) => (
      wall.y + wall.height - ((index + 1) * floorHeightMm / totalHeightMm) * wall.height
    )),
    openings,
  };
}
