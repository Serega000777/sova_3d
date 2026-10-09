import assert from "node:assert/strict";
import test from "node:test";

import { sceneTransformValues } from "../src/scene.ts";

const identity = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

test("a finite affine scene transform is flattened row-major", () => {
  const translated = identity.map((row) => [...row]);
  translated[0]![3] = 120;
  assert.deepEqual(sceneTransformValues(translated), translated.flat());
});

test("malformed, non-finite and out-of-range scene transforms fail closed", () => {
  assert.throws(() => sceneTransformValues(identity.slice(0, 3)), /invalid scene transform/);
  assert.throws(
    () => sceneTransformValues(identity.map((row) => row.map((item) => (item === 1 ? NaN : item)))),
    /invalid scene transform/,
  );
  const huge = identity.map((row) => [...row]);
  huge[0]![3] = 1_000_001;
  assert.throws(() => sceneTransformValues(huge), /invalid scene transform/);
});

test("non-affine and collapsed scene transforms fail closed", () => {
  const perspective = identity.map((row) => [...row]);
  perspective[3]![0] = 0.1;
  assert.throws(() => sceneTransformValues(perspective), /invalid scene transform/);
  const collapsed = identity.map((row) => [...row]);
  collapsed[2]![2] = 0;
  assert.throws(() => sceneTransformValues(collapsed), /invalid scene transform/);
});
