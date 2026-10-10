import assert from "node:assert/strict";
import test from "node:test";

import { planFootprintFromNode, sceneTransformValues } from "../src/scene.ts";

const identity = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

function baseNode(overrides: Partial<Parameters<typeof planFootprintFromNode>[0]> = {}) {
  return {
    id: "chair_1",
    name: "Chair",
    kind: "object",
    footprint_mm: [480, 520],
    world_transform: identity,
    effective_visible: true,
    ...overrides,
  };
}

test("a furniture node's world position and Z-rotation project onto the plan", () => {
  const rotated90 = [
    [0, -1, 0, 1000],
    [1, 0, 0, 2000],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
  ];
  const footprint = planFootprintFromNode(baseNode({ world_transform: rotated90 }));
  assert.ok(footprint);
  assert.deepEqual(footprint.at, [1000, 2000]);
  assert.equal(footprint.rotationDeg, 90);
  assert.equal(footprint.widthMm, 480);
  assert.equal(footprint.depthMm, 520);
  assert.equal(footprint.nodeId, "chair_1");
  assert.equal(footprint.label, "Chair");
});

test("a footprint overlay skips groups, hidden nodes and nodes without a declared footprint", () => {
  assert.equal(planFootprintFromNode(baseNode({ kind: "group" })), null);
  assert.equal(planFootprintFromNode(baseNode({ effective_visible: false })), null);
  assert.equal(planFootprintFromNode(baseNode({ footprint_mm: null })), null);
  assert.equal(planFootprintFromNode(baseNode({ footprint_mm: [0, 520] })), null);
  assert.equal(planFootprintFromNode(baseNode({ footprint_mm: [480] })), null);
});

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
