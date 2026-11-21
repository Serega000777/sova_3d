export const FRAGMENT_RESTORATION_BOUNDARIES = [
  "x_min",
  "x_max",
  "y_min",
  "y_max",
  "z_min",
  "z_max",
] as const;

export type FragmentRestorationBoundary = (typeof FRAGMENT_RESTORATION_BOUNDARIES)[number];

export type FragmentRestorationProposal = {
  sourceVersionId: string;
  body: {
    tolerance_mm: number;
    threads: true;
    restore_missing_half: FragmentRestorationBoundary | null;
    reinforce_thickness_percent: number | null;
  };
};

export function buildFragmentRestorationProposal(input: {
  sourceVersionId: string;
  toleranceMm: number;
  boundary: FragmentRestorationBoundary | null;
  reinforce: boolean;
  reinforcementPercent: number;
}): FragmentRestorationProposal {
  if (!Number.isFinite(input.toleranceMm) || input.toleranceMm <= 0.01 || input.toleranceMm > 5) {
    throw new Error("Допуск должен быть больше 0,01 и не больше 5 мм.");
  }
  let reinforcement: number | null = null;
  if (input.reinforce) {
    if (
      !Number.isFinite(input.reinforcementPercent)
      || input.reinforcementPercent <= 0
      || input.reinforcementPercent > 50
    ) {
      throw new Error("Усиление должно быть больше 0 и не больше 50%.");
    }
    if (input.boundary === "z_min" || input.boundary === "z_max") {
      throw new Error("Усиление толщины нельзя совмещать с восстановлением по оси Z.");
    }
    reinforcement = input.reinforcementPercent;
  }
  return {
    sourceVersionId: input.sourceVersionId,
    body: {
      tolerance_mm: input.toleranceMm,
      threads: true,
      restore_missing_half: input.boundary,
      reinforce_thickness_percent: reinforcement,
    },
  };
}

