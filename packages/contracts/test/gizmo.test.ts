import assert from "node:assert/strict";
import test from "node:test";

import { linearGizmoValue, rotationGizmoValue } from "../src/gizmo.ts";

test("linear gizmo maps screen distance into a bounded magnitude", () => {
  assert.equal(linearGizmoValue(100, 36, 0.72, 10, 1000), 150);
  assert.equal(linearGizmoValue(100, -3600, 0.72, 10, 1000), 10);
  assert.equal(linearGizmoValue(100, 3600, 0.72, 10, 1000), 1000);
});

test("linear gizmo rejects invalid calibration without inventing movement", () => {
  assert.equal(linearGizmoValue(125, 30, 0, 10, 1000), 125);
  assert.equal(linearGizmoValue(125, Number.NaN, 1, 10, 1000), 125);
});

test("rotation gizmo follows the shortest signed arc across the angle seam", () => {
  const degrees = (value: number) => (value * Math.PI) / 180;
  assert.equal(rotationGizmoValue(0, degrees(170), degrees(-170)), 20);
  assert.equal(rotationGizmoValue(0, degrees(-170), degrees(170)), -20);
});

test("rotation gizmo preserves the starting value and clamps the operation contract", () => {
  assert.equal(rotationGizmoValue(45, 0, Math.PI / 2), 135);
  assert.equal(rotationGizmoValue(350, 0, Math.PI / 2), 359);
  assert.equal(rotationGizmoValue(45, Number.NaN, 0), 45);
});
