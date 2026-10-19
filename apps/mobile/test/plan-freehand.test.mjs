import assert from "node:assert/strict";
import test from "node:test";

import {
  FREEHAND_MIN_SPAN_PX,
  finishFreehandStroke,
  updateFreehandStroke,
} from "../src/plan-freehand.ts";

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
