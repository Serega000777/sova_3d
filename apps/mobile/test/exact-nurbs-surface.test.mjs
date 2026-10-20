import assert from "node:assert/strict";
import test from "node:test";

import { buildMobileNurbsSurface } from "../src/exact-nurbs-surface.ts";

const valid = {
  controlPointsText: "10, 0, 0; 10, 0, 20\n10, 10, 0; 10, 10, 20\n0, 10, 0; 0, 10, 20",
  weightsText: "1, 1\n0.7071067811865476, 0.7071067811865476\n1, 1",
  uDegree: 2,
  vDegree: 1,
  uKnotsText: "0, 1",
  vKnotsText: "0, 1",
  uMultiplicitiesText: "3, 3",
  vMultiplicitiesText: "2, 2",
  thicknessText: "2",
};

test("mobile builds the exact bounded rational NURBS surface request", () => {
  const built = buildMobileNurbsSurface(valid);
  assert.equal(built.issue, null);
  assert.deepEqual(built.operation, {
    type: "nurbs_surface",
    control_points_mm: [
      [[10, 0, 0], [10, 0, 20]],
      [[10, 10, 0], [10, 10, 20]],
      [[0, 10, 0], [0, 10, 20]],
    ],
    weights: [[1, 1], [0.7071067811865476, 0.7071067811865476], [1, 1]],
    u_degree: 2,
    v_degree: 1,
    u_knots: [0, 1],
    v_knots: [0, 1],
    u_multiplicities: [3, 3],
    v_multiplicities: [2, 2],
    thickness_mm: 2,
    tolerance_mm: 1e-5,
  });
});

test("mobile rejects malformed NURBS surface grids before creating a job", () => {
  assert.equal(buildMobileNurbsSurface({
    ...valid,
    controlPointsText: "0, 0, 0; 0, 0, 10\n10, 0, 0",
  }).issue, "control_grid");
  assert.equal(buildMobileNurbsSurface({
    ...valid,
    weightsText: "1, 1\n1, 0\n1, 1",
  }).issue, "weight_grid");
  assert.equal(buildMobileNurbsSurface({
    ...valid,
    controlPointsText: "0, 0, 0; 0, 0, 10\n0, 0, 20; 0, 0, 30\n0, 0, 40; 0, 0, 50",
    weightsText: "1, 1\n1, 1\n1, 1",
  }).issue, "collapsed_grid");
});

test("mobile independently validates U/V bases and thickness bounds", () => {
  assert.equal(buildMobileNurbsSurface({ ...valid, uMultiplicitiesText: "2, 2" }).issue, "u_basis");
  assert.equal(buildMobileNurbsSurface({ ...valid, vDegree: 2 }).issue, "v_basis");
  assert.equal(buildMobileNurbsSurface({ ...valid, thicknessText: "10000.1" }).issue, "thickness");
});
