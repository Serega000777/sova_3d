import assert from "node:assert/strict";
import test from "node:test";

import type { FacadeCompatibility } from "@physical-ai/contracts";

import { facadePreviewGeometry, facadeSpanMm } from "../src/lib/facade-fit-preview.ts";

const compatibility: FacadeCompatibility = {
  project_id: "10000000-0000-4000-8000-000000000001",
  project_name: "House",
  version_id: "10000000-0000-4000-8000-000000000002",
  status: "complete",
  reason: null,
  matched_openings: 2,
  total_openings: 2,
  facade_length_mm: 8_000,
  facade_width_mm: 6_000,
  floor_height_mm: 3_000,
  floors: 2,
  openings: [
    {
      opening_id: "front-upstairs",
      kind: "window",
      side: "front",
      floor: 2,
      center_mm: 4_000,
      width_mm: 1_000,
      height_mm: 1_200,
      sill_mm: 900,
      bottom_mm: 3_900,
      matches: [{
        version_id: "10000000-0000-4000-8000-000000000003",
        label: "Window",
        size_mm: [250, 1_000, 1_200],
      }],
    },
    {
      opening_id: "right-door",
      kind: "door",
      side: "right",
      floor: 1,
      center_mm: 2_000,
      width_mm: 900,
      height_mm: 2_100,
      sill_mm: 0,
      bottom_mm: 0,
      matches: [{
        version_id: "10000000-0000-4000-8000-000000000004",
        label: "Door",
        size_mm: [250, 900, 2_100],
      }],
    },
  ],
};

test("facade sides use the proven house span", () => {
  assert.equal(facadeSpanMm(compatibility, "front"), 8_000);
  assert.equal(facadeSpanMm(compatibility, "right"), 6_000);
});

test("an addressed upper-floor opening keeps its absolute saved elevation", () => {
  const geometry = facadePreviewGeometry(compatibility, "front");
  assert.ok(geometry);
  assert.equal(geometry.floorLines.length, 1);
  assert.equal(geometry.openings.length, 1);
  const opening = geometry.openings[0];
  assert.ok(opening.y < geometry.floorLines[0]);
  assert.equal(opening.opening_id, "front-upstairs");
});

test("invalid or incomplete facade evidence fails closed", () => {
  assert.equal(facadePreviewGeometry({ ...compatibility, floors: null }, "front"), null);
  assert.equal(facadePreviewGeometry({ ...compatibility, facade_length_mm: 0 }, "front"), null);
  const forged = {
    ...compatibility,
    openings: [{ ...compatibility.openings[0], bottom_mm: 5_500, height_mm: 1_200 }],
  };
  assert.deepEqual(facadePreviewGeometry(forged, "front")?.openings, []);
});
