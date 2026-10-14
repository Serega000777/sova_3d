import assert from "node:assert/strict";
import { test } from "node:test";

import { calibratedPhotoDistanceMm } from "../src/photo-measurement.ts";

test("calibrated photo measurements respect horizontal and vertical pixel scales", () => {
  assert.equal(calibratedPhotoDistanceMm([[0, 0], [0.5, 0]], 1000, 500, 200), 100);
  assert.equal(calibratedPhotoDistanceMm([[0, 0], [0, 1]], 1000, 500, 200), 100);
});

test("calibrated photo measurements fail closed for incomplete or invalid input", () => {
  assert.equal(calibratedPhotoDistanceMm([[0, 0]], 1000, 500, 200), null);
  assert.equal(calibratedPhotoDistanceMm([[0, 0], [1.1, 0]], 1000, 500, 200), null);
  assert.equal(calibratedPhotoDistanceMm([[0, 0], [1, 0]], 0, 500, 200), null);
});
