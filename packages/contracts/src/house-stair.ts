/**
 * Client-side mirror of the server's bounded winder-turn stair rules, shared by the web and
 * mobile house creators so both give the same immediate feedback. The API and the worker still
 * revalidate the exact request; this never replaces them.
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
