import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMobileSketchSegment,
  scaleMobileSketchSegment,
} from "../src/exact-sketch-curves.ts";

test("mobile exact sketch builds bounded interpolating splines", () => {
  const valid = buildMobileSketchSegment({
    kind: "spline",
    start: [0, 0],
    end: [20, 0],
    splinePointsText: "5, 4\n15, 4",
  });
  assert.deepEqual(valid, {
    segment: { kind: "spline", through_points_mm: [[5, 4], [15, 4]] },
    issue: null,
  });

  assert.equal(buildMobileSketchSegment({
    kind: "spline",
    start: [0, 0],
    end: [20, 0],
    splinePointsText: "0, 0",
  }).issue, "spline");
  assert.equal(buildMobileSketchSegment({
    kind: "spline",
    start: [0, 0],
    end: [20, 0],
    splinePointsText: "not-a-point",
  }).issue, "spline");
});

test("mobile exact sketch accepts a clamped rational NURBS segment", () => {
  const valid = buildMobileSketchSegment({
    kind: "nurbs",
    start: [10, 0],
    end: [0, 10],
    nurbsControlPointsText: "10, 10",
    nurbsDegree: 2,
    nurbsWeightsText: "1, 0.7071067811865476, 1",
    nurbsKnotsText: "0, 1",
    nurbsMultiplicitiesText: "3, 3",
  });
  assert.equal(valid.issue, null);
  assert.equal(valid.segment.kind, "nurbs");
  assert.deepEqual(valid.segment.control_points_mm, [[10, 10]]);

  const scaled = scaleMobileSketchSegment(valid.segment, 2);
  assert.deepEqual(scaled.control_points_mm, [[20, 20]]);
  assert.deepEqual(scaled.weights, valid.segment.weights);
});

test("mobile exact sketch rejects malformed NURBS bases before a job", () => {
  const base = {
    kind: "nurbs",
    start: [10, 0],
    end: [0, 10],
    nurbsControlPointsText: "10, 10",
    nurbsDegree: 2,
    nurbsWeightsText: "1, 1, 1",
    nurbsKnotsText: "0, 1",
    nurbsMultiplicitiesText: "3, 3",
  };
  assert.equal(buildMobileSketchSegment({ ...base, nurbsWeightsText: "1, 1" }).issue, "nurbs");
  assert.equal(buildMobileSketchSegment({ ...base, nurbsKnotsText: "1, 0" }).issue, "nurbs");
  assert.equal(buildMobileSketchSegment({ ...base, nurbsMultiplicitiesText: "2, 2" }).issue, "nurbs");
  assert.equal(buildMobileSketchSegment({ ...base, nurbsDegree: 5 }).issue, "nurbs");
  assert.equal(buildMobileSketchSegment({ ...base, nurbsControlPointsText: "10, 0" }).issue, "nurbs");
});
