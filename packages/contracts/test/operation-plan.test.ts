import assert from "node:assert/strict";
import test from "node:test";

import { circularArcSegment } from "../src/operation-plan.ts";

test("circular sketch arc preserves its exact center and direction", () => {
  assert.deepEqual(
    circularArcSegment([0, 0], [20, 0], [10, 0], true),
    { kind: "arc", center_mm: [10, 0], clockwise: true },
  );
});

test("circular sketch arc fails closed for invalid or unequal radii", () => {
  assert.equal(circularArcSegment([0, 0], [20, 0], [0, 0]), null);
  assert.equal(circularArcSegment([0, 0], [20, 0], [9, 0]), null);
  assert.equal(circularArcSegment([0, 0], [20, 0], [Number.NaN, 0]), null);
});

test("circular sketch arc uses the same absolute tolerance as the API", () => {
  assert.notEqual(circularArcSegment([0, 0], [20.000_005, 0], [10, 0]), null);
  assert.equal(circularArcSegment([0, 0], [20.000_02, 0], [10, 0]), null);
});
