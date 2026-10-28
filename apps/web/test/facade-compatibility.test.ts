import assert from "node:assert/strict";
import test from "node:test";

import type { FacadeCompatibility, Project } from "@physical-ai/contracts";

import { verifiedFacadeCompatibility } from "../src/lib/facade-compatibility.ts";

const project = { id: "project-1", head_version_id: "version-1" } as Project;
const report = {
  project_id: "project-1",
  project_name: "House",
  version_id: "version-1",
  status: "complete",
  reason: null,
  matched_openings: 1,
  total_openings: 1,
  openings: [{
    opening_id: "front-window-1",
    kind: "window",
    side: "front",
    floor: 0,
    center_mm: 2_000,
    width_mm: 1_200,
    height_mm: 1_400,
    sill_mm: 900,
    bottom_mm: 900,
    matches: [{ version_id: "module-1", label: "Window", size_mm: [120, 1_200, 1_400] }],
  }],
  facade_length_mm: 10_000,
  facade_width_mm: 8_000,
  floor_height_mm: 3_000,
  floors: 2,
} satisfies FacadeCompatibility;

test("M05 accepts only a project-head-bound coherent facade compatibility report", () => {
  assert.equal(verifiedFacadeCompatibility(report, project), report);
  assert.equal(verifiedFacadeCompatibility({ ...report, project_id: "project-2" }, project), null);
  assert.equal(verifiedFacadeCompatibility({ ...report, version_id: "version-2" }, project), null);
  assert.equal(verifiedFacadeCompatibility({ ...report, matched_openings: 0 }, project), null);
  assert.equal(verifiedFacadeCompatibility({ ...report, total_openings: 2 }, project), null);
  assert.equal(verifiedFacadeCompatibility({ ...report, status: "partial" }, project), null);
  assert.equal(verifiedFacadeCompatibility({
    ...report,
    openings: [report.openings[0], report.openings[0]],
    total_openings: 2,
    matched_openings: 2,
  }, project), null);
});
