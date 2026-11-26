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

/**
 * Per-wall inset of every upper floor and the roof, mirroring `upper_floor_setback_sides_mm`.
 * X runs along the house length; `yMinMm` is the stair "left" wall and `yMaxMm` the "right" one.
 */
export interface UpperFloorSetbackSides {
  xMinMm: number;
  xMaxMm: number;
  yMinMm: number;
  yMaxMm: number;
}

export const UPPER_FLOOR_SETBACK_LIMITS = { sideMm: [0, 10_000], minUpperFloorMm: 2_000 } as const;

/** Effective insets: explicit per-side values win over the symmetric setback. */
export function upperFloorInsets(
  symmetricMm: number,
  sides?: UpperFloorSetbackSides | null,
): UpperFloorSetbackSides {
  return sides ?? { xMinMm: symmetricMm, xMaxMm: symmetricMm, yMinMm: symmetricMm, yMaxMm: symmetricMm };
}

export type UpperFloorSetbackProblem = "side" | "empty" | "upper_floor";

/** Mirror the server's per-side setback bounds; `null` means the request may be sent. */
export function checkUpperFloorSetbackSides(
  sides: UpperFloorSetbackSides,
  houseLengthMm: number,
  houseWidthMm: number,
): UpperFloorSetbackProblem | null {
  const values = [sides.xMinMm, sides.xMaxMm, sides.yMinMm, sides.yMaxMm];
  if (!values.every((value) => within(value, UPPER_FLOOR_SETBACK_LIMITS.sideMm))) return "side";
  if (!values.some((value) => value > 0)) return "empty";
  const min = UPPER_FLOOR_SETBACK_LIMITS.minUpperFloorMm;
  if (houseLengthMm - sides.xMinMm - sides.xMaxMm < min || houseWidthMm - sides.yMinMm - sides.yMaxMm < min) {
    return "upper_floor";
  }
  return null;
}

export type UpperFloorSetbackLevelsProblem = UpperFloorSetbackProblem | "levels" | "overhang";

/**
 * Mirror the server's `upper_floor_setbacks_mm` rules: exactly one entry per upper floor (floor 2
 * first), a non-zero profile, every level at least 2000 × 2000 mm and each level standing inside
 * the one below it. `null` means the request may be sent.
 */
export function checkUpperFloorSetbackLevels(
  levels: readonly UpperFloorSetbackSides[],
  floors: number,
  houseLengthMm: number,
  houseWidthMm: number,
): UpperFloorSetbackLevelsProblem | null {
  if (levels.length !== floors - 1 || levels.length === 0) return "levels";
  const sideLimits = UPPER_FLOOR_SETBACK_LIMITS.sideMm;
  const values = levels.flatMap((level) => [level.xMinMm, level.xMaxMm, level.yMinMm, level.yMaxMm]);
  if (!values.every((value) => within(value, sideLimits))) return "side";
  if (!values.some((value) => value > 0)) return "empty";
  const min = UPPER_FLOOR_SETBACK_LIMITS.minUpperFloorMm;
  let below: UpperFloorSetbackSides = { xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 };
  for (const level of levels) {
    if (houseLengthMm - level.xMinMm - level.xMaxMm < min || houseWidthMm - level.yMinMm - level.yMaxMm < min) {
      return "upper_floor";
    }
    if (level.xMinMm < below.xMinMm || level.xMaxMm < below.xMaxMm || level.yMinMm < below.yMinMm || level.yMaxMm < below.yMaxMm) {
      return "overhang";
    }
    below = level;
  }
  return null;
}

/**
 * The tightest inset on every wall across all upper levels. One stair/shaft rises through every
 * upper floor, so fitting it inside this envelope is the same as fitting it inside each level.
 */
export function stackedUpperFloorInsets(levels: readonly UpperFloorSetbackSides[]): UpperFloorSetbackSides {
  return levels.reduce<UpperFloorSetbackSides>(
    (acc, level) => ({
      xMinMm: Math.max(acc.xMinMm, level.xMinMm),
      xMaxMm: Math.max(acc.xMaxMm, level.xMaxMm),
      yMinMm: Math.max(acc.yMinMm, level.yMinMm),
      yMaxMm: Math.max(acc.yMaxMm, level.yMaxMm),
    }),
    { xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 },
  );
}

export const UPPER_FLOOR_SETBACK_LEVELS_PROBLEM_TEXT: Record<"levels" | "overhang", { ru: string; en: string }> = {
  levels: {
    ru: "Задайте отступы для каждого верхнего этажа.",
    en: "Give setbacks for every upper floor.",
  },
  overhang: {
    ru: "Каждый верхний этаж должен стоять внутри нижнего: отступ этажа 3 не меньше отступа этажа 2 с каждой стороны.",
    en: "Each upper floor must stand inside the one below: floor 3 needs at least floor 2's setback on every side.",
  },
};

export function upperFloorSetbackProblemText(
  problem: UpperFloorSetbackLevelsProblem,
): { ru: string; en: string } {
  return problem === "levels" || problem === "overhang"
    ? UPPER_FLOOR_SETBACK_LEVELS_PROBLEM_TEXT[problem]
    : UPPER_FLOOR_SETBACK_PROBLEM_TEXT[problem];
}

export const UPPER_FLOOR_SETBACK_PROBLEM_TEXT: Record<UpperFloorSetbackProblem, { ru: string; en: string }> = {
  side: { ru: "Отступ каждой стороны должен быть 0–10 000 мм.", en: "Each side setback must be 0–10,000 mm." },
  empty: {
    ru: "Укажите хотя бы одну сторону с отступом больше нуля или выключите отступ по сторонам.",
    en: "Give at least one side a positive setback or turn per-side setbacks off.",
  },
  upper_floor: {
    ru: "Отступы должны оставить верхний этаж не меньше 2000 × 2000 мм.",
    en: "The setbacks must leave an upper floor of at least 2,000 × 2,000 mm.",
  },
};

/** Whether an aligned stair box keeps 350 mm from the ground walls and the inset upper walls. */
function stairBoxFits(
  minX: number,
  minY: number,
  extentX: number,
  extentY: number,
  houseLengthMm: number,
  houseWidthMm: number,
  insets: UpperFloorSetbackSides,
): boolean {
  return minX >= CLEARANCE_MM + insets.xMinMm
    && minX + extentX <= houseLengthMm - CLEARANCE_MM - insets.xMaxMm
    && minY >= CLEARANCE_MM + insets.yMinMm
    && minY + extentY <= houseWidthMm - CLEARANCE_MM - insets.yMaxMm;
}

/** Same placement rule as the server: centred along X, wall-side or centred across Y. */
function placedMinY(placement: "left" | "center" | "right", extentY: number, houseWidthMm: number): number {
  if (placement === "left") return CLEARANCE_MM;
  if (placement === "right") return houseWidthMm - CLEARANCE_MM - extentY;
  return (houseWidthMm - extentY) / 2;
}

/**
 * Fit of any aligned stair bounding box (straight, L, U, winder or spiral) placed exactly like the
 * server: 350 mm from the ground walls and from every inset upper-floor wall.
 */
export function stairFootprintFits(input: {
  footprint: { x: number; y: number };
  placement: "left" | "center" | "right";
  houseLengthMm: number;
  houseWidthMm: number;
  insets: UpperFloorSetbackSides;
}): boolean {
  return stairBoxFits(
    (input.houseLengthMm - input.footprint.x) / 2,
    placedMinY(input.placement, input.footprint.y, input.houseWidthMm),
    input.footprint.x,
    input.footprint.y,
    input.houseLengthMm,
    input.houseWidthMm,
    input.insets,
  );
}

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
  /** Per-side insets; when present they replace `upperFloorSetbackMm`. */
  upperFloorSetbackSides?: UpperFloorSetbackSides | null;
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
  const insets = upperFloorInsets(input.upperFloorSetbackMm, input.upperFloorSetbackSides);
  const sideInset = input.placement === "left" ? insets.yMinMm : input.placement === "right" ? insets.yMaxMm : 0;
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
  // A wall-side stair keeps 350 mm from the ground-floor wall, so a setback on that side cuts into it.
  else if (sideInset > 0) problem = "setback_placement";
  else if (!stairBoxFits(
    (input.houseLengthMm - footprint.x) / 2,
    placedMinY(input.placement, footprint.y, input.houseWidthMm),
    footprint.x,
    footprint.y,
    input.houseLengthMm,
    input.houseWidthMm,
    insets,
  )) {
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
    ru: "Лестница с забежными ступенями не ставится к стене, над которой отступает верхний этаж: выберите центр или другую сторону.",
    en: "A winder stair cannot stand against a wall the upper floor is set back from: centre it or use the other side.",
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
  /** Per-side insets; when present they replace `upperFloorSetbackMm`. */
  upperFloorSetbackSides?: UpperFloorSetbackSides | null;
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
  const insets = upperFloorInsets(input.upperFloorSetbackMm, input.upperFloorSetbackSides);
  const fits = stairBoxFits(
    (input.houseLengthMm - input.diameterMm) / 2,
    placedMinY(input.placement, input.diameterMm, input.houseWidthMm),
    input.diameterMm,
    input.diameterMm,
    input.houseLengthMm,
    input.houseWidthMm,
    insets,
  );
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
