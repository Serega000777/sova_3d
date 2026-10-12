import assert from "node:assert/strict";
import test from "node:test";

import { projectMaterialTriangleUv } from "../src/interior-material.ts";

test("material UV projection uses object-local millimetres and every dominant axis", () => {
  assert.deepEqual(
    projectMaterialTriangleUv([[10, 20, 30], [10, 120, 30], [10, 20, 230]], 100),
    [[0.2, 0.3], [1.2, 0.3], [0.2, 2.3]],
  );
  assert.deepEqual(
    projectMaterialTriangleUv([[10, 20, 30], [110, 20, 30], [10, 20, 230]], 100),
    [[0.1, 0.3], [1.1, 0.3], [0.1, 2.3]],
  );
  assert.deepEqual(
    projectMaterialTriangleUv([[10, 20, 30], [110, 20, 30], [10, 120, 30]], 100),
    [[0.1, 0.2], [1.1, 0.2], [0.1, 1.2]],
  );
});

test("material UV projection rejects an invalid repeat scale", () => {
  assert.throws(() => projectMaterialTriangleUv([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 0));
});
