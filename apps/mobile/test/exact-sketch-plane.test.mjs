import assert from "node:assert/strict";
import test from "node:test";

import { buildMobileSketchPlane } from "../src/exact-sketch-plane.ts";

test("mobile arbitrary sketch plane keeps the declared frame and offsets by true millimetres", () => {
  const built = buildMobileSketchPlane({
    originText: ["1", "2", "3"],
    normalText: ["0", "1", "1"],
    xDirectionText: ["2", "0", "0"],
    heightText: "14,1421356237",
  });
  assert.equal(built.issue, null);
  assert.deepEqual(built.frame.origin_mm, [1, 2, 3]);
  assert.deepEqual(built.frame.normal, [0, 1, 1]);
  assert.deepEqual(built.frame.x_direction, [2, 0, 0]);
  assert.ok(Math.abs(built.frame.top_origin_mm[0] - 1) < 1e-9);
  assert.ok(Math.abs(built.frame.top_origin_mm[1] - 12) < 1e-9);
  assert.ok(Math.abs(built.frame.top_origin_mm[2] - 13) < 1e-9);
});

test("mobile arbitrary sketch plane rejects malformed frames before a job", () => {
  const base = {
    originText: ["0", "0", "0"],
    normalText: ["0", "0", "1"],
    xDirectionText: ["1", "0", "0"],
    heightText: "30",
  };
  assert.equal(buildMobileSketchPlane({ ...base, originText: ["x", "0", "0"] }).issue, "origin");
  assert.equal(buildMobileSketchPlane({ ...base, normalText: ["0", "0", "0"] }).issue, "normal");
  assert.equal(buildMobileSketchPlane({ ...base, xDirectionText: ["0", "0", "0"] }).issue, "x_direction");
  assert.equal(buildMobileSketchPlane({ ...base, xDirectionText: ["1", "0", "1"] }).issue, "perpendicular");
  assert.equal(buildMobileSketchPlane({ ...base, heightText: "10000.1" }).issue, "height");
});
