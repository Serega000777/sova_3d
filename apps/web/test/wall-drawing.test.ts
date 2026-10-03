/** T-238: snap-to-grid/corner and hit-testing logic for the freeform wall-drawing canvas,
 *  kept separate from WallDrawingCanvas.tsx so it is testable without a DOM or canvas. */
import assert from "node:assert/strict";
import test from "node:test";

import type { PlanWall } from "@physical-ai/contracts";

import {
  GRID_STEP_MM,
  hitWallIndex,
  nearestEndpoint,
  rectangleWalls,
  snapPoint,
  snapToGrid,
} from "../src/lib/wall-drawing.ts";

test("snapToGrid rounds to the nearest 100mm step", () => {
  assert.equal(snapToGrid(149), 100);
  assert.equal(snapToGrid(151), 200);
  assert.equal(snapToGrid(-149), -100);
  assert.equal(snapToGrid(0), 0);
  assert.equal(snapToGrid(1230, 500), 1000);
});

test("nearestEndpoint finds an existing wall corner within tolerance", () => {
  const walls: PlanWall[] = [{ a: [0, 0], b: [4000, 0], thickness_mm: 120 }];
  assert.deepEqual(nearestEndpoint([30, -20], walls, 50), [0, 0]);
  assert.deepEqual(nearestEndpoint([4010, 5], walls, 50), [4000, 0]);
  assert.equal(nearestEndpoint([2000, 2000], walls, 50), null);
});

test("nearestEndpoint prefers the closest corner when two are in range", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [100, 0], thickness_mm: 120 },
    { a: [90, 0], b: [90, 500], thickness_mm: 120 },
  ];
  // (96, 0) is 4mm from (100, 0) and 6mm from (90, 0) — the nearer one wins
  assert.deepEqual(nearestEndpoint([96, 0], walls, 50), [100, 0]);
});

test("snapPoint snaps to a corner before falling back to the grid", () => {
  const walls: PlanWall[] = [{ a: [0, 0], b: [4000, 0], thickness_mm: 120 }];
  assert.deepEqual(snapPoint([30, 20], walls, 50), [0, 0]); // corner wins
  assert.deepEqual(snapPoint([2030, 2060], walls, 50), [snapToGrid(2030), snapToGrid(2060)]); // out of range, grid wins
});

test("snapPoint falls back to the grid when there are no walls yet", () => {
  assert.deepEqual(snapPoint([149, 251], [], 50), [100, 300]);
});

test("GRID_STEP_MM matches the documented 100mm drawing step", () => {
  assert.equal(GRID_STEP_MM, 100);
});

test("hitWallIndex finds the wall under a point, accounting for its thickness", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [4000, 0], thickness_mm: 200 }, // half-thickness extends 100mm off the line
  ];
  assert.equal(hitWallIndex([2000, 90], walls, 20), 0); // inside the wall's visual stroke
  assert.equal(hitWallIndex([2000, 200], walls, 20), null); // well clear of the stroke
});

test("hitWallIndex returns the nearest wall when several are in tolerance", () => {
  const walls: PlanWall[] = [
    { a: [0, 0], b: [4000, 0], thickness_mm: 20 },
    { a: [0, 50], b: [4000, 50], thickness_mm: 20 },
  ];
  assert.equal(hitWallIndex([2000, 5], walls, 200), 0);
  assert.equal(hitWallIndex([2000, 45], walls, 200), 1);
});

test("hitWallIndex returns null for an empty wall list", () => {
  assert.equal(hitWallIndex([0, 0], [], 50), null);
});

test("rectangleWalls closes a drag from corner to corner into four walls", () => {
  const walls = rectangleWalls([0, 0], [4000, 3000], 120);
  assert.equal(walls.length, 4);
  assert.deepEqual(
    walls.map((w) => w.a),
    [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
  );
  assert.deepEqual(
    walls.map((w) => w.b),
    [[4000, 0], [4000, 3000], [0, 3000], [0, 0]],
  );
  assert.ok(walls.every((w) => w.thickness_mm === 120));
});

test("rectangleWalls works regardless of drag direction", () => {
  const fromBottomRight = rectangleWalls([4000, 3000], [0, 0], 120);
  assert.equal(fromBottomRight.length, 4);
  // still closes: every wall end is shared with exactly one other wall end
  const ends = fromBottomRight.flatMap((w) => [w.a.join(","), w.b.join(",")]);
  const counts = new Map<string, number>();
  for (const end of ends) counts.set(end, (counts.get(end) ?? 0) + 1);
  assert.ok([...counts.values()].every((count) => count === 2));
});
