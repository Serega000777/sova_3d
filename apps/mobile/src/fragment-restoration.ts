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
  restore_missing_half: FragmentRestorationBoundary | null;
  reinforce_thickness_percent: number | null;
};

export type FragmentRestorationProposal = {
  sourceVersionId: string;
  body: FragmentRestorationBody;
};

export function fragmentRestorationPreviewTransform(
  boundary: FragmentRestorationBoundary,
  size: { x: number; y: number; z: number },
): {
  axis: "x" | "y" | "z";
  mirrorScale: -1;
  mirrorOffsetMm: number;
  planeOffsetMm: number;
} {
  const axis = boundary[0] as "x" | "y" | "z";
  const extent = size[axis];
  if (!Number.isFinite(extent) || extent <= 0) {
    throw new Error("Для зеркального предпросмотра нужен положительный габарит модели.");
  }
  const direction = boundary.endsWith("_min") ? -1 : 1;
  return {
    axis,
    mirrorScale: -1,
    mirrorOffsetMm: direction * extent,
    planeOffsetMm: direction * extent / 2,
  };
}

function finiteDecimal(value: string): number {
  return Number(value.trim().replace(",", "."));
}
export function buildCadReconstructionProposal({
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

export function buildFragmentRestorationProposal(
  input: Parameters<typeof buildCadReconstructionProposal>[0],
): FragmentRestorationProposal {
  if (!input.boundary) {
    throw new Error("Укажите границу, на которой заканчивается сохранившаяся половина.");
  }
  return buildCadReconstructionProposal(input);
}
