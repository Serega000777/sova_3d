import assert from "node:assert/strict";
import test from "node:test";

import {
  emptyExteriorSectionCounts,
  exteriorCoveragePercent,
  normalizeExteriorSectionCounts,
  uncoveredExteriorSections,
} from "../src/exterior-capture.ts";

test("T-232 requires coverage of all four facades but keeps roof capture optional", () => {
  const counts = { front: 8, right: 8, back: 8, left: 8, roof: 0 };
  assert.deepEqual(uncoveredExteriorSections(counts), []);
  assert.equal(exteriorCoveragePercent(counts), 100);
});

test("T-232 reports the exact exterior directions still uncovered", () => {
  const counts = emptyExteriorSectionCounts();
  counts.front = 8;
  counts.right = 3;
  assert.deepEqual(uncoveredExteriorSections(counts).map((section) => section.id), ["right", "back", "left"]);
  assert.equal(exteriorCoveragePercent(counts), 34);
});

test("persisted capture counts are normalized before resume", () => {
  assert.deepEqual(normalizeExteriorSectionCounts({ front: 9.8, right: -1, roof: "4" }), {
    front: 9,
    right: 0,
    back: 0,
    left: 0,
    roof: 4,
  });
});
