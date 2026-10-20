import type { Vec3 } from "@physical-ai/contracts";

export type MobileSketchPlaneIssue =
  | "origin"
  | "normal"
  | "x_direction"
  | "perpendicular"
  | "height";

function parseVector(values: [string, string, string]): Vec3 {
  return values.map((value) => Number(value.replace(",", "."))) as Vec3;
}

function length(vector: Vec3): number {
  return Math.hypot(...vector);
}

export function buildMobileSketchPlane({
  originText,
  normalText,
  xDirectionText,
  heightText,
}: {
  originText: [string, string, string];
  normalText: [string, string, string];
  xDirectionText: [string, string, string];
  heightText: string;
}): {
  frame: {
    origin_mm: Vec3;
    top_origin_mm: Vec3;
    normal: Vec3;
    x_direction: Vec3;
  } | null;
  issue: MobileSketchPlaneIssue | null;
} {
  const origin = parseVector(originText);
  if (origin.some((value) => !Number.isFinite(value))) {
    return { frame: null, issue: "origin" };
  }
  const normal = parseVector(normalText);
  const normalLength = length(normal);
  if (normal.some((value) => !Number.isFinite(value)) || normalLength <= 1e-9) {
    return { frame: null, issue: "normal" };
  }
  const xDirection = parseVector(xDirectionText);
  const xLength = length(xDirection);
  if (xDirection.some((value) => !Number.isFinite(value)) || xLength <= 1e-9) {
    return { frame: null, issue: "x_direction" };
  }
  const cosine = normal.reduce(
    (sum, value, index) => sum + value * xDirection[index],
    0,
  ) / (normalLength * xLength);
  if (Math.abs(cosine) > 1e-6) {
    return { frame: null, issue: "perpendicular" };
  }
  const height = Number(heightText.replace(",", "."));
  if (!Number.isFinite(height) || height <= 0 || height > 10_000) {
    return { frame: null, issue: "height" };
  }
  const unitNormal = normal.map((value) => value / normalLength) as Vec3;
  return {
    frame: {
      origin_mm: origin,
      top_origin_mm: origin.map(
        (value, index) => value + unitNormal[index] * height,
      ) as Vec3,
      normal,
      x_direction: xDirection,
    },
    issue: null,
  };
}
