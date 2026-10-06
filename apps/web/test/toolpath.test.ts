import assert from "node:assert/strict";
import test from "node:test";

import { parseToolpath } from "../src/lib/toolpath.ts";

test("machine G-code becomes a complete coloured layer preview", () => {
  const preview = parseToolpath(`
G90
; layer 1/2 z=0.2 height=0.2
G1 Z0.200 F600
; TYPE:perimeter
G1 X10 Y10 F6000
G1 X20 Y10 E0.8 F3000
; TYPE:infill
G1 X12 Y12 F6000
G1 X18 Y18 E0.5 F3000
; layer 2/2 z=0.4 height=0.2
G1 Z0.400 F600
; TYPE:support-interface
G1 X13 Y13 F6000
G1 X17 Y13 E0.4 F3000
`);

  assert.equal(preview.layers.length, 2);
  assert.equal(preview.segment_count, 5);
  assert.deepEqual(
    preview.layers[0].segments.map((segment) => segment.kind),
    ["perimeter", "travel", "infill"],
  );
  assert.deepEqual(
    preview.layers[1].segments.map((segment) => segment.kind),
    ["travel", "support-interface"],
  );
  assert.deepEqual(preview.bounds, { min: [10, 10], max: [20, 18] });
});

test("legacy untyped extrusion stays visible instead of being discarded", () => {
  const preview = parseToolpath("; layer 1/1 z=0.2 height=0.2\nG1 X0 Y0\nG1 X1 Y1 E0.1\n");
  assert.equal(preview.layers[0].segments[0].kind, "unknown");
});

test("a skirt emitted before the first layer marker belongs to layer one", () => {
  const preview = parseToolpath(
    "G1 Z0.2\n; TYPE:skirt\nG1 X0 Y0\nG1 X2 Y0 E0.1\n; layer 1/1 z=0.2 height=0.2\n",
  );
  assert.equal(preview.layers[0].segments[0].kind, "skirt");
  assert.equal(preview.segment_count, 1);
});
