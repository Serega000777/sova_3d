import {
  sitePlanFromProvenance,
  type Job,
  type SitePlan,
  type Version,
} from "@physical-ai/contracts";

export const SITE_SIDES = ["north", "east", "south", "west"] as const;
export type SiteSide = typeof SITE_SIDES[number];
export type HouseFootprintDimensions = {
  length_mm: number;
  width_mm: number;
};

function finiteRange(value: number, minimum: number, maximum: number): boolean {
  return Number.isFinite(value) && value >= minimum && value <= maximum;
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function validRuleSource(value: string): boolean {
  if ([...value].length < 9
    || [...value].length > 500
    || value !== value.trim()
    || [...value].some((character) => character.charCodeAt(0) < 32)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.username === ""
      && url.password === ""
      && url.search === ""
      && url.hash === "";
  } catch {
    return false;
  }
}

export function houseBoundaryClearances(
  plan: SitePlan,
  house: HouseFootprintDimensions,
): Record<SiteSide, number> | null {
  if (!finiteRange(house.length_mm, 2_000, 50_000)
    || !finiteRange(house.width_mm, 2_000, 50_000)) return null;
  const angle = plan.house_rotation_deg * Math.PI / 180;
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  const footprint = [-house.length_mm / 2, house.length_mm / 2].flatMap((x) => (
    [-house.width_mm / 2, house.width_mm / 2].map((y) => ({
      x: plan.house_x_mm + cosine * x - sine * y,
      y: plan.house_y_mm + sine * x + cosine * y,
    }))
  ));
  const xs = footprint.map((point) => point.x);
  const ys = footprint.map((point) => point.y);
  return {
    north: plan.plot_width_mm / 2 - Math.max(...ys),
    east: plan.plot_length_mm / 2 - Math.max(...xs),
    south: plan.plot_width_mm / 2 + Math.min(...ys),
    west: plan.plot_length_mm / 2 + Math.min(...xs),
  };
}

export function sitePlanProblem(
  plan: SitePlan,
  house: HouseFootprintDimensions,
): string | null {
  if (!finiteRange(plan.plot_length_mm, 5_000, 200_000)
    || !finiteRange(plan.plot_width_mm, 5_000, 200_000)) {
    return "Размеры участка должны быть от 5 000 до 200 000 мм.";
  }
  if (!finiteRange(plan.house_x_mm, -100_000, 100_000)
    || !finiteRange(plan.house_y_mm, -100_000, 100_000)
    || !finiteRange(plan.house_rotation_deg, -180, 180)) {
    return "Проверьте положение и поворот дома.";
  }
  if (!finiteRange(plan.minimum_boundary_clearance_mm ?? 500, 500, 50_000)) {
    return "Минимальный отступ должен быть от 500 до 50 000 мм.";
  }
  const elevations = plan.corner_elevations_mm ?? [];
  if (elevations.length !== 4
    || elevations.some((value) => !Number.isFinite(value))
    || Math.max(...elevations) - Math.min(...elevations) > 10_000) {
    return "Нужны четыре отметки рельефа с перепадом не более 10 000 мм.";
  }
  if (plan.path_points_mm.length < 2 || plan.path_points_mm.length > 16) {
    return "Дорожке нужны от 2 до 16 точек.";
  }
  let previous: number[] | null = null;
  for (const point of plan.path_points_mm) {
    if (point.length !== 2
      || !finiteRange(point[0]!, -plan.plot_length_mm / 2, plan.plot_length_mm / 2)
      || !finiteRange(point[1]!, -plan.plot_width_mm / 2, plan.plot_width_mm / 2)) {
      return "Все точки дорожки должны находиться внутри участка.";
    }
    if (previous && Math.hypot(point[0]! - previous[0]!, point[1]! - previous[1]!) < 1) {
      return "Соседние точки дорожки должны различаться хотя бы на 1 мм.";
    }
    previous = point;
  }
  if (!finiteRange(plan.path_width_mm, 300, 5_000)) {
    return "Ширина дорожки должна быть от 300 до 5 000 мм.";
  }
  const fenceSides = plan.fence_sides ?? [];
  if (new Set(fenceSides).size !== fenceSides.length
    || fenceSides.some((side) => !SITE_SIDES.includes(side))) {
    return "Проверьте выбранные стороны забора.";
  }
  if (!finiteRange(plan.fence_height_mm, 400, 4_000)
    || !finiteRange(plan.fence_post_spacing_mm, 1_000, 5_000)) {
    return "Проверьте высоту забора и шаг столбов.";
  }
  const rules = plan.boundary_rule_set;
  if (rules) {
    if (!rules.jurisdiction.trim() || rules.jurisdiction.trim().length > 120
      || !rules.title.trim() || rules.title.trim().length > 200
      || !rules.source_version.trim() || rules.source_version.trim().length > 80
      || !validRuleSource(rules.source_url)
      || !validDate(rules.effective_date)
      || SITE_SIDES.some((side) => !finiteRange(rules.required_clearances_mm[side], 500, 50_000))) {
      return "Проверьте источник и все четыре отступа owner-declared правил.";
    }
  }
  const measuredClearances = houseBoundaryClearances(plan, house);
  if (!measuredClearances) return "Не удалось подтвердить размеры дома из исходной версии.";
  const minimumClearance = plan.minimum_boundary_clearance_mm ?? 500;
  const failedSides = SITE_SIDES.filter((side) => measuredClearances[side] < Math.max(
    minimumClearance,
    rules?.required_clearances_mm[side] ?? minimumClearance,
  ));
  if (failedSides.length > 0) {
    return `Повернутый контур дома нарушает отступы: ${failedSides.join(", ")}.`;
  }
  return null;
}

function canonicalSitePlan(value: SitePlan): SitePlan | null {
  return sitePlanFromProvenance({
    ...value,
    minimum_boundary_clearance_mm: value.minimum_boundary_clearance_mm ?? 500,
    boundary_rule_set: value.boundary_rule_set ?? null,
  });
}

export function sameSitePlan(left: SitePlan, right: SitePlan): boolean {
  const first = canonicalSitePlan(left);
  const second = canonicalSitePlan(right);
  return first !== null && second !== null && JSON.stringify(first) === JSON.stringify(second);
}

export function verifiedSitePlanJobVersionId(
  job: Job,
  expectedJobId: string,
  sourceVersionId: string,
  expected: SitePlan,
): string | null {
  if (job.id !== expectedJobId
    || job.type !== "compose_site_plan"
    || job.status !== "succeeded"
    || !job.result
    || typeof job.result !== "object") return null;
  const result = job.result as Record<string, unknown>;
  if (result.source_version_id !== sourceVersionId || typeof result.version_id !== "string") return null;
  const saved = sitePlanFromProvenance(result.site_plan);
  return saved && sameSitePlan(saved, expected) ? result.version_id : null;
}

export function verifiedSitePlanVersion(
  version: Version,
  expectedVersionId: string,
  projectId: string,
  sourceVersionId: string,
  expected: SitePlan,
): boolean {
  const saved = sitePlanFromProvenance(
    (version.provenance as { site_plan?: unknown } | null)?.site_plan,
  );
  return version.id === expectedVersionId
    && version.project_id === projectId
    && version.parent_version_id === sourceVersionId
    && saved !== null
    && sameSitePlan(saved, expected);
}
