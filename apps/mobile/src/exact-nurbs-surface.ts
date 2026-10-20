import type { Vec3 } from "@physical-ai/contracts";

export interface MobileNurbsSurfaceDraft {
  controlPointsText: string;
  weightsText: string;
  uDegree: number;
  vDegree: number;
  uKnotsText: string;
  vKnotsText: string;
  uMultiplicitiesText: string;
  vMultiplicitiesText: string;
  thicknessText: string;
}

export interface MobileNurbsSurfaceOperation {
  type: "nurbs_surface";
  control_points_mm: Vec3[][];
  weights: number[][];
  u_degree: number;
  v_degree: number;
  u_knots: number[];
  v_knots: number[];
  u_multiplicities: number[];
  v_multiplicities: number[];
  thickness_mm: number;
  tolerance_mm: number;
}

export type MobileNurbsSurfaceIssue =
  | "control_grid"
  | "weight_grid"
  | "u_basis"
  | "v_basis"
  | "collapsed_grid"
  | "thickness";

function numberList(value: string): number[] {
  return value
    .split(/[,;\s]+/)
    .filter(Boolean)
    .map((part) => Number(part.replace(",", ".")));
}

function controlGrid(value: string): Vec3[][] {
  return value
    .split(/\n+/)
    .filter((row) => row.trim())
    .map((row) =>
      row.split(";").map((point) =>
        point
          .trim()
          .split(/[,\s]+/)
          .filter(Boolean)
          .map(Number) as Vec3,
      ),
    );
}

function weightGrid(value: string): number[][] {
  return value
    .split(/\n+/)
    .filter((row) => row.trim())
    .map(numberList);
}

function validBasis(
  poleCount: number,
  degree: number,
  knots: number[],
  multiplicities: number[],
): boolean {
  return Number.isInteger(degree)
    && degree >= 1
    && degree <= 5
    && degree < poleCount
    && knots.length >= 2
    && knots.length <= 16
    && knots.length === multiplicities.length
    && knots.every((value) => Number.isFinite(value) && Math.abs(value) <= 1_000_000)
    && knots.slice(1).every((value, index) => knots[index] < value)
    && multiplicities.every((value) => Number.isInteger(value) && value >= 1 && value <= 6)
    && multiplicities[0] === degree + 1
    && multiplicities.at(-1) === degree + 1
    && multiplicities.slice(1, -1).every((value) => value <= degree)
    && multiplicities.reduce((sum, value) => sum + value, 0) === poleCount + degree + 1;
}

function subtract(left: Vec3, right: Vec3): Vec3 {
  return [left[0] - right[0], left[1] - right[1], left[2] - right[2]];
}

function crossLength(left: Vec3, right: Vec3): number {
  return Math.hypot(
    left[1] * right[2] - left[2] * right[1],
    left[2] * right[0] - left[0] * right[2],
    left[0] * right[1] - left[1] * right[0],
  );
}

export function buildMobileNurbsSurface(
  draft: MobileNurbsSurfaceDraft,
): { operation: MobileNurbsSurfaceOperation | null; issue: MobileNurbsSurfaceIssue | null } {
  const controls = controlGrid(draft.controlPointsText);
  const uPoles = controls.length;
  const vPoles = controls[0]?.length ?? 0;
  if (
    uPoles < 2
    || uPoles > 16
    || vPoles < 2
    || vPoles > 16
    || controls.some((row) =>
      row.length !== vPoles
      || row.some((point) => point.length !== 3 || point.some((value) => !Number.isFinite(value))),
    )
  ) {
    return { operation: null, issue: "control_grid" };
  }

  const weights = weightGrid(draft.weightsText);
  if (
    weights.length !== uPoles
    || weights.some((row) =>
      row.length !== vPoles
      || row.some((value) => !Number.isFinite(value) || value <= 0 || value > 1_000_000),
    )
  ) {
    return { operation: null, issue: "weight_grid" };
  }

  const uKnots = numberList(draft.uKnotsText);
  const vKnots = numberList(draft.vKnotsText);
  const uMultiplicities = numberList(draft.uMultiplicitiesText);
  const vMultiplicities = numberList(draft.vMultiplicitiesText);
  if (!validBasis(uPoles, draft.uDegree, uKnots, uMultiplicities)) {
    return { operation: null, issue: "u_basis" };
  }
  if (!validBasis(vPoles, draft.vDegree, vKnots, vMultiplicities)) {
    return { operation: null, issue: "v_basis" };
  }

  const origin = controls[0][0];
  const vectors = controls.flat().map((point) => subtract(point, origin));
  const spansPatch = vectors.some((left, leftIndex) =>
    vectors.slice(leftIndex + 1).some((right) => crossLength(left, right) > 1e-10),
  );
  if (!spansPatch) return { operation: null, issue: "collapsed_grid" };

  const thickness = Number(draft.thicknessText.replace(",", "."));
  if (!Number.isFinite(thickness) || thickness <= 0 || thickness > 10_000) {
    return { operation: null, issue: "thickness" };
  }

  return {
    operation: {
      type: "nurbs_surface",
      control_points_mm: controls,
      weights,
      u_degree: draft.uDegree,
      v_degree: draft.vDegree,
      u_knots: uKnots,
      v_knots: vKnots,
      u_multiplicities: uMultiplicities,
      v_multiplicities: vMultiplicities,
      thickness_mm: thickness,
      tolerance_mm: 1e-5,
    },
    issue: null,
  };
}
