/** T-235 / T-236: selections become coordinates the worker can find, and failures read well. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  describeEditFailure,
  faceAnchor,
  footprintSegments,
  selectionToPoints,
  sourceTriangleCount,
} from "../src/mesh-edit.ts";
import { buildTopology, componentAtHit } from "../src/topology.ts";

function cubeSoup(): number[] {
  const v = [
    [0, 0, 0], [40, 0, 0], [40, 40, 0], [0, 40, 0],
    [0, 0, 40], [40, 0, 40], [40, 40, 40], [0, 40, 40],
  ];
  const tris = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ];
  return tris.flatMap((t) => t.flatMap((i) => v[i] as number[]));
}

test("each component kind becomes the right number of coordinates", () => {
  const topology = buildTopology(cubeSoup(), null);
  const vertex = selectionToPoints(topology, "vertex", [0, 1]);
  assert.equal(vertex.points_mm.length, 2);
  const edge = selectionToPoints(topology, "edge", [0]);
  assert.equal(edge.points_mm.length, 2);
  const face = selectionToPoints(topology, "face", [0, 1]);
  assert.equal(face.points_mm.length, 6);
  for (const point of face.points_mm) assert.ok(point.every((n) => n === 0 || n === 40));
});

test("a selected face carries the corners of its source triangle", () => {
  const topology = buildTopology(cubeSoup(), null);
  const id = componentAtHit(topology, "face", { sourceFace: 2, point: [30, 5, 40] }) as number;
  const points = selectionToPoints(topology, "face", [id]).points_mm;
  assert.deepEqual(points.map((p) => p[2]), [40, 40, 40]); // the top face
});

test("the source triangle count is what the viewer drew, welded or not", () => {
  assert.equal(sourceTriangleCount(buildTopology(cubeSoup(), null)), 12);
});

test("a face anchor is its centre and outward normal", () => {
  const topology = buildTopology(cubeSoup(), null);
  const id = componentAtHit(topology, "face", { sourceFace: 2, point: [30, 5, 40] }) as number;
  const anchor = faceAnchor(topology, id);
  assert.equal(anchor.at_mm[2], 40);
  assert.deepEqual(anchor.normal.map((n) => Math.round(n)), [0, 0, 1]);
});

test("failures read in the person's language and fall back to the worker's message", () => {
  assert.match(describeEditFailure("below_tolerance", "x", "en"), /smaller than the tolerance/);
  assert.match(describeEditFailure("below_tolerance", "x", "ru"), /меньше допуска/);
  assert.equal(describeEditFailure("something_new", "the worker said so", "en"), "the worker said so");
  assert.match(describeEditFailure(null, null, "ru"), /Не удалось/);
});

test("a footprint becomes closed outline segments", () => {
  const triangle: [number, number, number][] = [[0, 0, 0], [1, 0, 0], [0, 1, 0]];
  const segments = footprintSegments(triangle);
  assert.equal(segments.length, 3);
  assert.deepEqual(segments[2], [[0, 1, 0], [0, 0, 0]]);
});
