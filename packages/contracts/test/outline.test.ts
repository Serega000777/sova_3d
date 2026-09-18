/**
 * The rules that turn a drawn path into a region (T-113): the same for every client.
 * Runs on Node's own test runner with type stripping — no extra tooling.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type Point2,
  dominantAxis,
  isClosed,
  isStraight,
  pathToRegion,
  planeAxes,
  ribbon,
} from "../src/outline.ts";

const plate = { x: 60, y: 40, z: 8 };
const top = { axis: "z" as const, sign: "+" as const, offset_mm: 8 };

function bounds(points: Point2[]) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

test("the dominant axis of a normal, with its sign", () => {
  assert.deepEqual(dominantAxis({ x: 0.1, y: -0.05, z: 0.99 }), { axis: "z", sign: "+" });
  assert.deepEqual(dominantAxis({ x: -0.9, y: 0.3, z: 0.1 }), { axis: "x", sign: "-" });
  assert.deepEqual(planeAxes("z"), ["x", "y"]);
  assert.deepEqual(planeAxes("x"), ["y", "z"]);
});

test("a straight drag while editing becomes a rubber-band rectangle", () => {
  // a mouse produces many samples along one line, with a little jitter
  const path: Point2[] = Array.from({ length: 30 }, (_, i) => [10 + i, 10 + i * 0.5 + (i % 2) * 0.1]);
  assert.equal(isStraight(path), true);
  const selection = pathToRegion(path, { surface: top, modelSize: plate, bodyId: "body" });
  assert.ok(selection);
  assert.equal(selection.region.kind, "lasso");
  assert.equal(selection.region.points_mm.length, 4);
  assert.deepEqual(bounds(selection.region.points_mm), {
    minX: 10,
    maxX: 39,
    minY: 10,
    maxY: 24.6,
  });
  // and it reaches through the whole plate under the outline
  assert.equal(selection.region.depth_mm, 16);
  assert.equal(selection.region.offset_mm, 8);
  assert.equal(selection.surface_axis, "z");
  assert.equal(selection.target, "body");
});

test("a curved outline while editing is kept as drawn", () => {
  const circle: Point2[] = Array.from({ length: 40 }, (_, i) => {
    const angle = (i / 40) * Math.PI * 2;
    return [30 + 10 * Math.cos(angle), 20 + 10 * Math.sin(angle)];
  });
  assert.equal(isStraight(circle), false);
  const selection = pathToRegion(circle, { surface: top, modelSize: plate, bodyId: "body" });
  assert.ok(selection);
  assert.equal(selection.region.kind, "lasso");
  assert.equal(selection.region.points_mm.length, 40);
});

test("a sweep while painting is a band as wide as the brush", () => {
  const sweep: Point2[] = Array.from({ length: 50 }, (_, i) => [5 + i, 20]);
  const selection = pathToRegion(sweep, {
    surface: top,
    modelSize: plate,
    bodyId: "body",
    brushMm: 6,
  });
  assert.ok(selection);
  const box = bounds(selection.region.points_mm);
  assert.equal(box.minY, 17);
  assert.equal(box.maxY, 23);
  // square caps extend the band by half a brush at each end
  assert.equal(box.minX, 2);
  assert.equal(box.maxX, 57);
});

test("a closed loop while painting is filled, not stroked", () => {
  const loop: Point2[] = Array.from({ length: 24 }, (_, i) => {
    const angle = (i / 24) * Math.PI * 2;
    return [30 + 8 * Math.cos(angle), 20 + 8 * Math.sin(angle)];
  });
  assert.equal(isClosed(loop), true);
  const selection = pathToRegion(loop, {
    surface: top,
    modelSize: plate,
    bodyId: "body",
    brushMm: 6,
  });
  assert.ok(selection);
  assert.equal(selection.region.points_mm.length, 24); // the loop itself
});

test("a tap is not an outline, but a paint dab is", () => {
  const tap: Point2[] = [
    [10, 10],
    [10.05, 10.02],
  ];
  assert.equal(pathToRegion(tap, { surface: top, modelSize: plate, bodyId: "body" }), null);
  const dab = pathToRegion(tap, { surface: top, modelSize: plate, bodyId: "body", brushMm: 4 });
  assert.ok(dab);
  const box = bounds(dab.region.points_mm);
  assert.ok(box.maxX - box.minX >= 4 && box.maxY - box.minY >= 4);
});

test("a long sweep never exceeds the outline the API accepts", () => {
  const long: Point2[] = Array.from({ length: 2000 }, (_, i) => [i * 0.05, Math.sin(i / 50) * 5]);
  assert.ok(ribbon(long, 2).length <= 256);
});
