export const FRAGMENT_RESTORATION_BOUNDARIES = [
  "x_min",
  "x_max",
  "y_min",
  "y_max",
  "z_min",
  "z_max",
] as const;

export type FragmentRestorationBoundary = (typeof FRAGMENT_RESTORATION_BOUNDARIES)[number];

export type FragmentRestorationBody = {
  tolerance_mm: number;
  threads: true;
  restore_missing_half: FragmentRestorationBoundary;
  reinforce_thickness_percent: number | null;
};

export type FragmentRestorationProposal = {
  sourceVersionId: string;
  body: FragmentRestorationBody;
};

function finiteDecimal(value: string): number {
  return Number(value.trim().replace(",", "."));
}
export function buildFragmentRestorationProposal({
  sourceVersionId,
  tolerance,
  boundary,
  reinforce,
  reinforcementPercent,
}: {
  sourceVersionId: string;
  tolerance: string;
  boundary: FragmentRestorationBoundary | null;
  reinforce: boolean;
  reinforcementPercent: string;
}): FragmentRestorationProposal {
  const toleranceMm = finiteDecimal(tolerance);
  if (!Number.isFinite(toleranceMm) || toleranceMm <= 0.01 || toleranceMm > 5) {
    throw new Error("Допуск должен быть больше 0,01 и не больше 5 мм.");
  }
  if (!boundary) {
    throw new Error("Укажите границу, на которой заканчивается сохранившаяся половина.");
  }

  let reinforcedBy: number | null = null;
  if (reinforce) {
    reinforcedBy = finiteDecimal(reinforcementPercent);
    if (!Number.isFinite(reinforcedBy) || reinforcedBy <= 0 || reinforcedBy > 50) {
      throw new Error("Усиление должно быть больше 0 и не больше 50%.");
    }
    if (boundary === "z_min" || boundary === "z_max") {
      throw new Error("Усиление толщины нельзя совмещать с восстановлением по оси Z.");
    }
  }

  return {
    sourceVersionId,
    body: {
      tolerance_mm: toleranceMm,
      threads: true,
      restore_missing_half: boundary,
      reinforce_thickness_percent: reinforcedBy,
    },
  };
}
