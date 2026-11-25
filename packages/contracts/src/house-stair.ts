/**
 * Client-side mirrors of the server's bounded stair rules, shared by the web and mobile house
 * creators so both give the same immediate feedback. The API and the worker still revalidate
 * the exact request; these checks never replace them.
 */

export const WINDER_STAIR_LIMITS = {
  widthMm: [700, 2_000],
  treadMm: [200, 400],
  flightSteps: [3, 24],
  newelMm: [200, 500],
  risers: [10, 30],
  riseMm: [120, 220],
  strideMm: [550, 700],
} as const;

const WINDERS = 3;
const WALKLINE_OFFSET_MM = 300;
const CLEARANCE_MM = 350;

export type WinderStairProblem =
  | "width"
  | "tread"
  | "flight_steps"
  | "newel"
  | "risers"
  | "rise"
  | "stride"
  | "winder_stride"
  | "setback_placement"
  | "fit";

export interface WinderStairInput {
  widthMm: number;
  treadMm: number;
  lowerSteps: number;
  upperSteps: number;
  newelMm: number;
  placement: "left" | "center" | "right";
  houseLengthMm: number;
  houseWidthMm: number;
  floorHeightMm: number;
  /** Symmetric inset of the upper floors; 0 when the house has no setback. */
  upperFloorSetbackMm: number;
}

export interface WinderStairCheck {
  riserCount: number;
  riseMm: number;
  /** Arc going of each 30° winder on the walking line. */
  winderGoingMm: number;
  footprint: { x: number; y: number };
  problem: WinderStairProblem | null;
}

/** NaN and infinities are outside every range. */
function within(value: number, [low, high]: readonly [number, number]): boolean {
  return value >= low && value <= high;
}

export function checkWinderStair(input: WinderStairInput): WinderStairCheck {
  const riserCount = input.lowerSteps + WINDERS + input.upperSteps;
  const riseMm = input.floorHeightMm / riserCount;
  const winderGoingMm = (input.newelMm + WALKLINE_OFFSET_MM) * (Math.PI / 6);
  const turn = input.widthMm + input.newelMm;
  const footprint = {
    x: input.treadMm * input.lowerSteps + turn,
    y: turn + input.treadMm * input.upperSteps,
  };
  const limits = WINDER_STAIR_LIMITS;
  const margin = 2 * (CLEARANCE_MM + input.upperFloorSetbackMm);
  const flightOk = (steps: number) => Number.isInteger(steps) && within(steps, limits.flightSteps);
  let problem: WinderStairProblem | null = null;
  if (!within(input.widthMm, limits.widthMm)) problem = "width";
  else if (!within(input.treadMm, limits.treadMm)) problem = "tread";
  else if (!flightOk(input.lowerSteps) || !flightOk(input.upperSteps)) problem = "flight_steps";
  else if (!within(input.newelMm, limits.newelMm)) problem = "newel";
  else if (!within(riserCount, limits.risers)) problem = "risers";
  else if (!within(riseMm, limits.riseMm)) problem = "rise";
  else if (!within(2 * riseMm + input.treadMm, limits.strideMm)) problem = "stride";
  else if (!within(2 * riseMm + winderGoingMm, limits.strideMm)) problem = "winder_stride";
  // A wall-side stair keeps 350 mm from the ground-floor wall, so any setback would cut into it.
  else if (input.upperFloorSetbackMm > 0 && input.placement !== "center") problem = "setback_placement";
  else if (!(footprint.x <= input.houseLengthMm - margin && footprint.y <= input.houseWidthMm - margin)) {
    problem = "fit";
  }
  return { riserCount, riseMm, winderGoingMm, footprint, problem };
}

export const WINDER_STAIR_PROBLEM_TEXT: Record<WinderStairProblem, { ru: string; en: string }> = {
  width: { ru: "Ширина марша должна быть 700–2000 мм.", en: "Flight width must be 700–2000 mm." },
  tread: { ru: "Проступь должна быть 200–400 мм.", en: "Tread depth must be 200–400 mm." },
  flight_steps: { ru: "В каждом марше нужно 3–24 ступени.", en: "Each flight needs 3–24 steps." },
  newel: { ru: "Внутренний просвет должен быть 200–500 мм.", en: "The newel void must be 200–500 mm." },
  risers: {
    ru: "Нужно 10–30 подъёмов вместе с тремя забежными ступенями.",
    en: "Use 10–30 risers including the three winders.",
  },
  rise: { ru: "Высота подъёма должна быть 120–220 мм.", en: "Rise must be 120–220 mm." },
  stride: {
    ru: "2 × подъём + проступь должно быть 550–700 мм.",
    en: "2 × rise + tread must be 550–700 mm.",
  },
  winder_stride: {
    ru: "2 × подъём + проступь забежной ступени по линии хода должно быть 550–700 мм: измените внутренний просвет.",
    en: "2 × rise + winder going on the walking line must be 550–700 mm: change the newel void.",
  },
  setback_placement: {
    ru: "При отступе верхних этажей лестница с забежными ступенями ставится только по центру.",
    en: "With an upper-floor setback a winder stair can only be centred.",
  },
  fit: {
    ru: "Лестница с проёмом не помещается в контур с отступом 350 мм от стен.",
    en: "The stair and opening do not fit the footprint with 350 mm wall clearance.",
  },
};

export const SPIRAL_STAIR_LIMITS = {
  diameterMm: [1_400, 3_200],
  postDiameterMm: [100, 300],
  steps: [10, 20],
  sweepDeg: [180, 330],
  treadAngleDeg: [10, 30],
  clearWidthMm: [700, 1_400],
  goingMm: [200, 400],
  riseMm: [120, 220],
  strideMm: [550, 700],
} as const;

export type SpiralStairProblem =
  | "diameter"
  | "post"
  | "steps"
  | "sweep"
  | "rise"
  | "tread_angle"
  | "clear_width"
  | "going"
  | "stride"
  | "fit";

export interface SpiralStairInput {
  diameterMm: number;
  postDiameterMm: number;
  stepCount: number;
  sweepDeg: number;
  placement: "left" | "center" | "right";
  houseLengthMm: number;
  houseWidthMm: number;
  floorHeightMm: number;
  /** Symmetric inset of the upper floors; 0 when the house has no setback. */
  upperFloorSetbackMm: number;
}

export interface SpiralStairCheck {
  riseMm: number;
  treadAngleDeg: number;
  clearWidthMm: number;
  walklineRadiusMm: number;
  goingMm: number;
  footprint: { x: number; y: number };
  problem: SpiralStairProblem | null;
}

/** Mirror the exact server derivations for one circular-sector stair around a central post. */
export function checkSpiralStair(input: SpiralStairInput): SpiralStairCheck {
  const riseMm = input.floorHeightMm / input.stepCount;
  const treadAngleDeg = input.sweepDeg / input.stepCount;
  const clearWidthMm = (input.diameterMm - input.postDiameterMm) / 2;
  const walklineRadiusMm = (input.diameterMm + input.postDiameterMm) / 4;
  const goingMm = walklineRadiusMm * treadAngleDeg * Math.PI / 180;
  const footprint = { x: input.diameterMm, y: input.diameterMm };
  const limits = SPIRAL_STAIR_LIMITS;
  const inset = CLEARANCE_MM + input.upperFloorSetbackMm;
  const radius = input.diameterMm / 2;
  const centerY = input.placement === "left"
    ? CLEARANCE_MM + radius
    : input.placement === "right"
      ? input.houseWidthMm - CLEARANCE_MM - radius
      : input.houseWidthMm / 2;
  const fits = input.houseLengthMm / 2 - radius >= inset
    && input.houseLengthMm / 2 + radius <= input.houseLengthMm - inset
    && centerY - radius >= inset
    && centerY + radius <= input.houseWidthMm - inset;
  let problem: SpiralStairProblem | null = null;
  if (!within(input.diameterMm, limits.diameterMm)) problem = "diameter";
  else if (!within(input.postDiameterMm, limits.postDiameterMm)) problem = "post";
  else if (!Number.isInteger(input.stepCount) || !within(input.stepCount, limits.steps)) problem = "steps";
  else if (!within(input.sweepDeg, limits.sweepDeg)) problem = "sweep";
  else if (!within(riseMm, limits.riseMm)) problem = "rise";
  else if (!within(treadAngleDeg, limits.treadAngleDeg)) problem = "tread_angle";
  else if (!within(clearWidthMm, limits.clearWidthMm)) problem = "clear_width";
  else if (!within(goingMm, limits.goingMm)) problem = "going";
  else if (!within(2 * riseMm + goingMm, limits.strideMm)) problem = "stride";
  else if (!fits) problem = "fit";
  return { riseMm, treadAngleDeg, clearWidthMm, walklineRadiusMm, goingMm, footprint, problem };
}

export const SPIRAL_STAIR_PROBLEM_TEXT: Record<SpiralStairProblem, { ru: string; en: string }> = {
  diameter: { ru: "Диаметр лестницы должен быть 1400–3200 мм.", en: "Stair diameter must be 1400–3200 mm." },
  post: { ru: "Диаметр центрального столба должен быть 100–300 мм.", en: "Central post diameter must be 100–300 mm." },
  steps: { ru: "Нужно 10–20 ступеней.", en: "Use 10–20 steps." },
  sweep: { ru: "Суммарный поворот должен быть 180–330°.", en: "Total sweep must be 180–330°." },
  rise: { ru: "Высота подъёма должна быть 120–220 мм.", en: "Rise must be 120–220 mm." },
  tread_angle: { ru: "Угол одной ступени должен быть 10–30°.", en: "Each tread angle must be 10–30°." },
  clear_width: { ru: "Чистая ширина между столбом и краем должна быть 700–1400 мм.", en: "Clear width from post to edge must be 700–1400 mm." },
  going: { ru: "Проступь по средней линии хода должна быть 200–400 мм.", en: "Going on the middle walking line must be 200–400 mm." },
  stride: { ru: "2 × подъём + проступь по линии хода должно быть 550–700 мм.", en: "2 × rise + walking-line going must be 550–700 mm." },
  fit: { ru: "Круглая лестница и проём не помещаются с отступом 350 мм от стен и верхнего контура.", en: "The circular stair and opening do not fit with 350 mm clearance from walls and the upper footprint." },
};
