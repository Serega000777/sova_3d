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
    minimum_boundary_clearance_mm: 1750,
    corner_elevations_mm: [0, 50, 100, 25],
    path_points_mm: [[-1000, -500], [0, 0], [1000, 500]],
    fence_sides: ["north", "south"],
    house_dimensions_mm: [10_000, 8_000],
  };
  assert.deepEqual(sitePlanFromProvenance(saved), {
    ...DEFAULT_SITE_PLAN,
    house_x_mm: 1250,
    minimum_boundary_clearance_mm: 1750,
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
  assert.equal(sitePlanFromProvenance({ ...DEFAULT_SITE_PLAN, minimum_boundary_clearance_mm: null }), null);
});

test("legacy canonical site provenance keeps the former 500 mm boundary rule", () => {
  const legacy = structuredClone(DEFAULT_SITE_PLAN) as Record<string, unknown>;
  delete legacy.minimum_boundary_clearance_mm;
  assert.equal(sitePlanFromProvenance(legacy)?.minimum_boundary_clearance_mm, 500);
});

test("a complete owner-declared boundary source hydrates without becoming a legal claim", () => {
  const boundary_rule_set = {
    schema_version: 1 as const,
    authority_status: "owner_declared" as const,
    jurisdiction: "Example municipality",
    title: "Owner-selected source",
    source_url: "https://rules.example.test/setbacks",
    source_version: "2026.4",
    effective_date: "2026-04-01",
    required_clearances_mm: { north: 4000, east: 8000, south: 4500, west: 10000 },
  };
  assert.deepEqual(
    sitePlanFromProvenance({ ...DEFAULT_SITE_PLAN, boundary_rule_set })?.boundary_rule_set,
    boundary_rule_set,
  );
  assert.equal(
    sitePlanFromProvenance({
      ...DEFAULT_SITE_PLAN,
      boundary_rule_set: { ...boundary_rule_set, source_url: "http://rules.example.test" },
    }),
    null,
  );
  assert.equal(
    sitePlanFromProvenance({
      ...DEFAULT_SITE_PLAN,
      boundary_rule_set: {
        ...boundary_rule_set,
        source_url: "https://rules.example.test/setbacks?token=secret",
      },
    }),
    null,
  );
  assert.equal(
    sitePlanFromProvenance({
      ...DEFAULT_SITE_PLAN,
      boundary_rule_set: {
        ...boundary_rule_set,
        required_clearances_mm: { ...boundary_rule_set.required_clearances_mm, west: 50_001 },
      },
    }),
    null,
  );
});

test("Studio hydrates and rebuilds an existing site as a new immutable scene", () => {
  assert.match(projectPage, /sitePlanFromProvenance/);
  assert.match(projectPage, /sceneProvenance\.site_plan/);
  assert.match(projectPage, /Пересобрать участок/);
  assert.match(projectPage, /Заданный отступ до границы/);
  assert.match(projectPage, /Добавить версионированный источник правил/);
  assert.match(projectPage, /не подтверждает юридическую применимость или актуальность документа/);
  assert.match(projectPage, /заменяет только служебные рельеф, площадку, дорожку и забор/);
  assert.doesNotMatch(projectPage, /!sceneProvenance\.site_plan/);
});
