import type { SitePlan } from "@physical-ai/contracts";

export const DEFAULT_SITE_PLAN: SitePlan = {
  plot_length_mm: 30000,
  plot_width_mm: 20000,
  corner_elevations_mm: [0, 0, 0, 0],
  house_x_mm: 0,
  house_y_mm: 0,
  house_rotation_deg: 0,
  minimum_boundary_clearance_mm: 500,
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

function boundaryRuleSet(value: unknown): NonNullable<SitePlan["boundary_rule_set"]> | null {
  const source = record(value);
  if (!source || source.schema_version !== 1 || source.authority_status !== "owner_declared") {
    return null;
  }
  const expectedKeys = [
    "authority_status", "effective_date", "jurisdiction", "required_clearances_mm",
    "schema_version", "source_url", "source_version", "title",
  ];
  if (Object.keys(source).sort().join("\0") !== expectedKeys.join("\0")) return null;
  const textKeys = ["jurisdiction", "title", "source_url", "source_version", "effective_date"] as const;
  if (textKeys.some((key) => typeof source[key] !== "string" || !(source[key] as string).trim())) {
    return null;
  }
  let sourceUrl: URL;
  try {
    sourceUrl = new URL(source.source_url as string);
  } catch {
    return null;
  }
  if (
    sourceUrl.protocol !== "https:"
    || sourceUrl.username !== ""
    || sourceUrl.password !== ""
    || sourceUrl.search !== ""
    || sourceUrl.hash !== ""
  ) return null;
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(source.effective_date as string);
  if (!dateMatch) return null;
  const date = new Date(Date.UTC(Number(dateMatch[1]), Number(dateMatch[2]) - 1, Number(dateMatch[3])));
  if (date.toISOString().slice(0, 10) !== source.effective_date) return null;
  const clearances = record(source.required_clearances_mm);
  if (
    !clearances
    || Object.keys(clearances).sort().join("\0") !== "east\0north\0south\0west"
    || (["north", "east", "south", "west"] as const).some((side) => (
      !finite(clearances[side]) || (clearances[side] as number) < 500 || (clearances[side] as number) > 50_000
    ))
  ) {
    return null;
  }
  return {
    schema_version: 1,
    authority_status: "owner_declared",
    jurisdiction: (source.jurisdiction as string).trim(),
    title: (source.title as string).trim(),
    source_url: source.source_url as string,
    source_version: (source.source_version as string).trim(),
    effective_date: source.effective_date as string,
    required_clearances_mm: {
      north: clearances.north as number,
      east: clearances.east as number,
      south: clearances.south as number,
      west: clearances.west as number,
    },
  };
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
  const minimumClearance = source.minimum_boundary_clearance_mm === undefined
    ? 500
    : source.minimum_boundary_clearance_mm;
  if (!finite(minimumClearance)) return null;
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
  const ruleSet = source.boundary_rule_set == null
    ? null
    : boundaryRuleSet(source.boundary_rule_set);
  if (source.boundary_rule_set != null && !ruleSet) return null;
  return {
    plot_length_mm: source.plot_length_mm as number,
    plot_width_mm: source.plot_width_mm as number,
    corner_elevations_mm: [...elevations] as number[],
    house_x_mm: source.house_x_mm as number,
    house_y_mm: source.house_y_mm as number,
    house_rotation_deg: source.house_rotation_deg as number,
    minimum_boundary_clearance_mm: minimumClearance,
    ...(ruleSet ? { boundary_rule_set: ruleSet } : {}),
    path_points_mm: points.map((point) => [...point] as number[]),
    path_width_mm: source.path_width_mm as number,
    fence_sides: [...sides] as SitePlan["fence_sides"],
    fence_height_mm: source.fence_height_mm as number,
    fence_post_spacing_mm: source.fence_post_spacing_mm as number,
  };
}
