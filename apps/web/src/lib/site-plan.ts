import type { SitePlan } from "@physical-ai/contracts";

export const DEFAULT_SITE_PLAN: SitePlan = {
  plot_length_mm: 30000,
  plot_width_mm: 20000,
  corner_elevations_mm: [0, 0, 0, 0],
  house_x_mm: 0,
  house_y_mm: 0,
  house_rotation_deg: 0,
  path_points_mm: [[0, -10000], [0, -3000]],
  path_width_mm: 1200,
  fence_sides: ["north", "east", "south", "west"],
  fence_height_mm: 1500,
  fence_post_spacing_mm: 2500,
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Hydrate only a complete canonical site-job snapshot; partial/forged data stays unusable. */
export function sitePlanFromProvenance(value: unknown): SitePlan | null {
  const source = record(value);
  if (!source) return null;
  const numericKeys = [
    "plot_length_mm", "plot_width_mm", "house_x_mm", "house_y_mm",
    "house_rotation_deg", "path_width_mm", "fence_height_mm", "fence_post_spacing_mm",
  ] as const;
  if (numericKeys.some((key) => !finite(source[key]))) return null;
  const elevations = source.corner_elevations_mm;
  if (!Array.isArray(elevations) || elevations.length !== 4 || !elevations.every(finite)) return null;
  const points = source.path_points_mm;
  if (!Array.isArray(points) || points.length < 2 || points.length > 16) return null;
  if (!points.every((point) => Array.isArray(point) && point.length === 2 && point.every(finite))) {
    return null;
  }
  const sides = source.fence_sides;
  const allowed = new Set(["north", "east", "south", "west"] as const);
  if (!Array.isArray(sides) || !sides.every((side) => allowed.has(side))) return null;
  return {
    plot_length_mm: source.plot_length_mm as number,
    plot_width_mm: source.plot_width_mm as number,
    corner_elevations_mm: [...elevations] as number[],
    house_x_mm: source.house_x_mm as number,
    house_y_mm: source.house_y_mm as number,
    house_rotation_deg: source.house_rotation_deg as number,
    path_points_mm: points.map((point) => [...point] as number[]),
    path_width_mm: source.path_width_mm as number,
    fence_sides: [...sides] as SitePlan["fence_sides"],
    fence_height_mm: source.fence_height_mm as number,
    fence_post_spacing_mm: source.fence_post_spacing_mm as number,
  };
}
