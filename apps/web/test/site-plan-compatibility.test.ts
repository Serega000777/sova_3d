import assert from "node:assert/strict";
import test from "node:test";

import type { Project, SitePlanCompatibility } from "@physical-ai/contracts";

import { verifiedSitePlanCompatibility } from "../src/lib/site-plan-compatibility.ts";

const project = {
  id: "project-1",
  name: "Yard",
  head_version_id: "version-1",
} as Project;
const report = {
  project_id: "project-1",
  project_name: "Yard",
  version_id: "version-1",
  status: "compatible",
  reason: null,
  required_size_mm: [10_000, 8_000],
  available_size_mm: [10_000, 8_000],
  spare_size_mm: [0, 0],
  terrain_rotation_deg: 0,
  terrain_corner_delta_mm: [0, 25, -10, 5],
  terrain_max_delta_mm: 25,
} satisfies SitePlanCompatibility;

test("M07 accepts only a project-head-bound coherent site compatibility report", () => {
  assert.equal(verifiedSitePlanCompatibility(report, project), report);
  assert.equal(verifiedSitePlanCompatibility({ ...report, project_id: "project-2" }, project), null);
  assert.equal(verifiedSitePlanCompatibility({ ...report, version_id: "version-2" }, project), null);
  assert.equal(verifiedSitePlanCompatibility({ ...report, status: "rotated" }, project), null);
  assert.equal(verifiedSitePlanCompatibility({ ...report, spare_size_mm: [1, 0] }, project), null);
  assert.equal(verifiedSitePlanCompatibility({ ...report, terrain_rotation_deg: 90 }, project), null);
  assert.equal(verifiedSitePlanCompatibility({ ...report, terrain_max_delta_mm: 24 }, project), null);
});

test("M07 validates rotated, incompatible and unsupported reports without inventing fit", () => {
  const rotated = {
    ...report,
    status: "rotated",
    required_size_mm: [12_000, 8_000],
    available_size_mm: [8_000, 12_000],
    terrain_rotation_deg: 90,
  } satisfies SitePlanCompatibility;
  assert.equal(verifiedSitePlanCompatibility(rotated, project), rotated);
  assert.equal(verifiedSitePlanCompatibility({
    ...rotated,
    status: "incompatible",
    available_size_mm: [7_000, 7_000],
    spare_size_mm: null,
    terrain_rotation_deg: null,
    terrain_corner_delta_mm: null,
    terrain_max_delta_mm: null,
  }, project)?.status, "incompatible");
  assert.equal(verifiedSitePlanCompatibility({
    ...report,
    status: "unsupported",
    reason: "head_has_no_proven_site_plan",
    available_size_mm: null,
    spare_size_mm: null,
    terrain_rotation_deg: null,
    terrain_corner_delta_mm: null,
    terrain_max_delta_mm: null,
  }, project)?.status, "unsupported");
});
