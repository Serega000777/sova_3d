import assert from "node:assert/strict";
import test from "node:test";

import { isValidBuildingFloorPlans } from "../src/plan-link.ts";

const plan = {
  id: "floor-1",
  name: "Floor",
  walls: [
    { a: [0, 0], b: [4000, 0], thickness_mm: 120 },
    { a: [4000, 0], b: [4000, 3000], thickness_mm: 120 },
    { a: [4000, 3000], b: [0, 3000], thickness_mm: 120 },
    { a: [0, 3000], b: [0, 0], thickness_mm: 120 },
  ],
  openings: [],
  rooms: [{ name: "Room", outline: [[0, 0], [4000, 0], [4000, 3000], [0, 3000]] }],
};

test("multi-floor mobile plan lineage accepts measured unique levels", () => {
  assert.equal(
    isValidBuildingFloorPlans({
      version_id: "version-1",
      floor_height_mm: 3000,
      levels: [
        { index: 0, name: "1 этаж", elevation_mm: 0, plan },
        { index: 1, name: "2 этаж", elevation_mm: 3000, plan: { ...plan, id: "floor-2" } },
      ],
    }),
    true,
  );
});

test("multi-floor mobile plan lineage rejects duplicate or unmeasured levels", () => {
  const base = {
    version_id: "version-1",
    floor_height_mm: 3000,
    levels: [
      { index: 0, name: "1 этаж", elevation_mm: 0, plan },
      { index: 0, name: "2 этаж", elevation_mm: 3000, plan: { ...plan, id: "floor-2" } },
    ],
  };
  assert.equal(isValidBuildingFloorPlans(base), false);
  assert.equal(
    isValidBuildingFloorPlans({
      ...base,
      levels: [{ index: 0, name: "1 этаж", elevation_mm: Number.NaN, plan }],
    }),
    false,
  );
});
