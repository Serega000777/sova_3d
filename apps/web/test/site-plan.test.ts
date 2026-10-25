import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEFAULT_SITE_PLAN, sitePlanFromProvenance } from "../src/lib/site-plan.ts";

const projectPage = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("a canonical saved site plan hydrates the immutable recomposition form", () => {
  const saved = {
    ...DEFAULT_SITE_PLAN,
    schema_version: 1,
    house_x_mm: 1250,
    corner_elevations_mm: [0, 50, 100, 25],
    path_points_mm: [[-1000, -500], [0, 0], [1000, 500]],
    fence_sides: ["north", "south"],
    house_dimensions_mm: [10_000, 8_000],
  };
  assert.deepEqual(sitePlanFromProvenance(saved), {
    ...DEFAULT_SITE_PLAN,
    house_x_mm: 1250,
    corner_elevations_mm: [0, 50, 100, 25],
    path_points_mm: [[-1000, -500], [0, 0], [1000, 500]],
    fence_sides: ["north", "south"],
  });
});

test("partial or malformed provenance never becomes editable site input", () => {
  assert.equal(sitePlanFromProvenance(null), null);
  assert.equal(sitePlanFromProvenance({ ...DEFAULT_SITE_PLAN, path_points_mm: [[0, 0]] }), null);
  assert.equal(sitePlanFromProvenance({ ...DEFAULT_SITE_PLAN, corner_elevations_mm: [0, 0, 0] }), null);
  assert.equal(sitePlanFromProvenance({ ...DEFAULT_SITE_PLAN, fence_sides: ["ceiling"] }), null);
});

test("Studio hydrates and rebuilds an existing site as a new immutable scene", () => {
  assert.match(projectPage, /sitePlanFromProvenance/);
  assert.match(projectPage, /sceneProvenance\.site_plan/);
  assert.match(projectPage, /Пересобрать участок/);
  assert.match(projectPage, /заменяет только служебные рельеф, площадку, дорожку и забор/);
  assert.doesNotMatch(projectPage, /!sceneProvenance\.site_plan/);
});
