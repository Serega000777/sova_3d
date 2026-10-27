import assert from "node:assert/strict";
import test from "node:test";

import {
  BROKEN_PART_SECTIONS,
  brokenPartCoveragePercent,
  emptyBrokenPartSectionCounts,
  parseBrokenPartScaleMm,
  uncoveredBrokenPartSections,
} from "../src/broken-part-capture.ts";

test("broken-part capture requires whole, fracture and interior evidence", () => {
  assert.deepEqual(BROKEN_PART_SECTIONS.map((section) => section.targetFrames), [8, 4, 4]);
  assert.equal(brokenPartCoveragePercent(emptyBrokenPartSectionCounts), 0);
  assert.deepEqual(
    uncoveredBrokenPartSections({ whole: 8, fracture: 4, interior: 0 }).map((section) => section.id),
    ["interior"],
  );
  assert.equal(brokenPartCoveragePercent({ whole: 8, fracture: 4, interior: 4 }), 100);
});

test("broken-part metric scale requires one bounded user measurement", () => {
  assert.equal(parseBrokenPartScaleMm("95"), 95);
  assert.equal(parseBrokenPartScaleMm("95,5"), 95.5);
  for (const value of ["", "0", "0.5", "-1", "10001", "NaN", "Infinity"]) {
    assert.equal(parseBrokenPartScaleMm(value), null);
  }
});
