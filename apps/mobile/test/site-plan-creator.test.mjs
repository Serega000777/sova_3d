import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEFAULT_SITE_PLAN } from "@physical-ai/contracts";

import {
  sameSitePlan,
  houseBoundaryClearances,
  sitePlanProblem,
  verifiedSitePlanJobVersionId,
  verifiedSitePlanVersion,
} from "../src/site-plan-creator.ts";

function plan(overrides = {}) {
  return structuredClone({ ...DEFAULT_SITE_PLAN, ...overrides });
}

const house = { length_mm: 10_000, width_mm: 8_000 };

test("mobile site-plan draft enforces the bounded server shape", () => {
  assert.equal(sitePlanProblem(plan(), house), null);
  assert.match(sitePlanProblem(plan({ plot_length_mm: 4999 }), house), /5 000/);
  assert.match(sitePlanProblem(plan({ corner_elevations_mm: [0, 0, 0, 10001] }), house), /10 000/);
  assert.match(sitePlanProblem(plan({ path_points_mm: [[0, 0]] }), house), /2 до 16/);
  assert.match(sitePlanProblem(plan({ path_points_mm: [[0, 0], [0, 0]] }), house), /1 мм/);
  assert.match(sitePlanProblem(plan({ path_points_mm: [[0, 0], [20000, 0]] }), house), /внутри участка/);
  assert.match(sitePlanProblem(plan({ fence_post_spacing_mm: 999 }), house), /шаг столбов/);
});

test("owner-declared boundary source remains explicit and fail-closed", () => {
  const rules = {
    schema_version: 1,
    authority_status: "owner_declared",
    jurisdiction: "Москва",
    title: "Правила землепользования",
    source_url: "https://example.com/rules",
    source_version: "2026-11",
    effective_date: "2026-11-25",
    required_clearances_mm: { north: 3000, east: 3000, south: 3000, west: 3000 },
  };
  assert.equal(sitePlanProblem(plan({ boundary_rule_set: rules }), house), null);
  assert.match(sitePlanProblem(plan({ boundary_rule_set: { ...rules, source_url: "http://example.com" } }), house), /owner-declared/);
  assert.match(sitePlanProblem(plan({ boundary_rule_set: { ...rules, source_url: " https://example.com/rules" } }), house), /owner-declared/);
  assert.match(sitePlanProblem(plan({ boundary_rule_set: { ...rules, source_url: `https://example.com/${"a".repeat(481)}` } }), house), /owner-declared/);
  assert.match(sitePlanProblem(plan({ boundary_rule_set: { ...rules, source_url: "https://example.com/rules\u0007" } }), house), /owner-declared/);
  assert.match(sitePlanProblem(plan({ boundary_rule_set: { ...rules, effective_date: "2026-02-30" } }), house), /owner-declared/);
});

test("rotated house footprint is checked against all effective boundary clearances", () => {
  assert.deepEqual(houseBoundaryClearances(plan(), house), {
    north: 6000,
    east: 10000,
    south: 6000,
    west: 10000,
  });
  assert.match(
    sitePlanProblem(plan({ house_rotation_deg: 45, house_x_mm: 9000 }), house),
    /east/,
  );
  const rules = {
    schema_version: 1,
    authority_status: "owner_declared",
    jurisdiction: "Москва",
    title: "Правила землепользования",
    source_url: "https://example.com/rules",
    source_version: "2026-11",
    effective_date: "2026-11-25",
    required_clearances_mm: { north: 7000, east: 500, south: 500, west: 500 },
  };
  assert.match(sitePlanProblem(plan({ boundary_rule_set: rules }), house), /north/);
});

test("site-plan completion is bound to the exact source, result and immutable child", () => {
  const expected = plan();
  const result = {
    version_id: "version-2",
    source_version_id: "version-1",
    site_plan: { ...expected, schema_version: 1 },
  };
  const job = { id: "job-1", type: "compose_site_plan", status: "succeeded", result };
  assert.equal(verifiedSitePlanJobVersionId(job, "job-1", "version-1", expected), "version-2");
  assert.equal(verifiedSitePlanJobVersionId(job, "wrong-job", "version-1", expected), null);
  assert.equal(verifiedSitePlanJobVersionId({ ...job, type: "other" }, "job-1", "version-1", expected), null);
  assert.equal(verifiedSitePlanJobVersionId(job, "job-1", "wrong", expected), null);
  assert.equal(verifiedSitePlanJobVersionId({ ...job, result: { ...result, site_plan: { ...expected, path_width_mm: 999 } } }, "job-1", "version-1", expected), null);
  const version = {
    id: "version-2",
    project_id: "project-1",
    parent_version_id: "version-1",
    provenance: { site_plan: { ...expected, schema_version: 1 } },
  };
  assert.equal(verifiedSitePlanVersion(version, "version-2", "project-1", "version-1", expected), true);
  assert.equal(verifiedSitePlanVersion({ ...version, id: "wrong" }, "version-2", "project-1", "version-1", expected), false);
  assert.equal(verifiedSitePlanVersion({ ...version, parent_version_id: "wrong" }, "version-2", "project-1", "version-1", expected), false);
  assert.equal(sameSitePlan(expected, plan()), true);
});

test("project screen exposes the complete editor only for editable house lineage", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const creator = readFileSync(new URL("../src/SitePlanCreator.tsx", import.meta.url), "utf8");
  assert.match(project, /canEditWorkspace && hasHouseBoxLineage/);
  assert.match(project, /active\.id === project\.head_version\?\.id/);
  assert.match(project, /houseDimensions=/);
  assert.match(project, /sitePlanFromProvenance/);
  assert.match(project, /<SitePlanCreator/);
  assert.match(creator, /client\.composeSitePlan\(/);
  assert.match(creator, /client\.waitForJob\(/);
  assert.match(creator, /client\.getVersion\(/);
  assert.match(creator, /if \(!mounted\.current\) return/);
  assert.match(creator, /corner_elevations_mm\.map/);
  assert.match(creator, /path_points_mm\.map/);
  assert.match(creator, /SITE_SIDES\.map/);
  assert.match(creator, /owner-declared/);
});
