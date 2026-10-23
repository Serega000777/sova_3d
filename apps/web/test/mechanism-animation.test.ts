import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { hingedLidTransform } from "../src/lib/mechanism.ts";

test("hinged lid preview rotates around its declared X-axis pivot", () => {
  const closed = hingedLidTransform(0, 18);
  assert.deepEqual(closed, [
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 18],
    [0, 0, 0, 1],
  ]);
  const open = hingedLidTransform(90, 18);
  assert.ok(Math.abs(open[1]![1]!) < 1e-10);
  assert.equal(open[1]![2], -1);
  assert.equal(open[2]![1], 1);
  assert.equal(open[2]![3], 18);
});

test("Studio exposes generation and bounded kinematic validation", () => {
  const source = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  assert.match(source, /client\.buildHingedLid/);
  assert.match(source, /type="range"/);
  assert.match(source, /Прочность, износ/);
});
