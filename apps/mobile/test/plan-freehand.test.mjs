import assert from "node:assert/strict";
import test from "node:test";

import {
  FREEHAND_MIN_SPAN_PX,
  commitFreehandStroke,
  finishFreehandStroke,
  updateFreehandStroke,
} from "../src/plan-freehand.ts";

const base = {
  id: "stroke-1",
  author: "Tester",
  created_at: "2026-10-20T00:00:00.000Z",
  status: "open",
  note: "",
  colour: "#ff4d4f",
};

test("mobile freehand keeps a decimated live draft with the current endpoint", () => {
  let points = [[0, 0]];
  points = updateFreehandStroke(points, [1, 0], 1);
  points = updateFreehandStroke(points, [2, 0], 1);
  points = updateFreehandStroke(points, [2.5, 0], 1);

  assert.deepEqual(points[0], [0, 0]);
  assert.deepEqual(points.at(-1), [2.5, 0]);
  assert.ok(points.length < 4);
});

test("mobile freehand rejects taps and preserves a valid release point", () => {
  assert.equal(finishFreehandStroke([[0, 0]], [FREEHAND_MIN_SPAN_PX - 1, 0], 1), null);
  assert.equal(finishFreehandStroke([[0, 0], [0, 0]], [0, 0], 1), null);
  assert.equal(finishFreehandStroke([[0, 0]], [20, 0], Number.NaN), null);

  const complete = finishFreehandStroke(
    [[0, 0], [4, 0], [Number.NaN, 2]],
    [FREEHAND_MIN_SPAN_PX + 2, 0],
    1,
  );
  assert.ok(complete);
  assert.deepEqual(complete[0], [0, 0]);
  assert.deepEqual(complete.at(-1), [FREEHAND_MIN_SPAN_PX + 2, 0]);
  assert.ok(complete.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y)));
});

test("mobile freehand produces no history value during updates and one on release", () => {
  const existing = [{ ...base, id: "existing", kind: "pin", at: [50, 50], number: 1 }];
  let points = [[0, 0]];
  let historyCommits = 0;

  for (let x = 1; x <= 20; x += 1) points = updateFreehandStroke(points, [x, x % 2], 1);
  assert.equal(historyCommits, 0);
  assert.equal(existing.length, 1);

  const completed = commitFreehandStroke(existing, base, points, [24, 0], 1);
  if (completed) historyCommits += 1;
  assert.ok(completed);
  assert.equal(historyCommits, 1);
  assert.equal(existing.length, 1);
  assert.equal(completed.annotations.length, 2);
  assert.equal(completed.annotations[1], completed.annotation);
});
