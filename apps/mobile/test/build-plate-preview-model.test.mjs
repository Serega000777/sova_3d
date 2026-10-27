import assert from "node:assert/strict";
import test from "node:test";

import { buildPlatePreviewModel } from "../src/build-plate-preview.ts";

const layout = {
  layout_bed_mm: [200, 100, 180],
  parts: [{
    name: "part_01",
    extents_mm: [40, 20, 10],
    plate_offset_mm: [10, 15, 0],
    plate_rotation_deg: 90,
  }],
  dowels: [{
    name: "dowel_01",
    diameter_mm: 10,
    plate_offset_mm: [100, 50, 0],
  }],
};

test("build plate preview maps real millimetres into bed percentages", () => {
  const model = buildPlatePreviewModel(layout);
  assert.ok(model);
  assert.deepEqual(model.shapes[0], {
    id: "part_01",
    kind: "part",
    label: "1 · 90°",
    leftPct: 5,
    bottomPct: 15,
    widthPct: 10,
    heightPct: 40,
  });
  assert.deepEqual(model.shapes[1], {
    id: "dowel_01",
    kind: "dowel",
    label: "D1",
    leftPct: 50,
    bottomPct: 50,
    widthPct: 5,
    heightPct: 10,
  });
});

test("invalid bed, geometry and out-of-bed placement fail closed", () => {
  assert.equal(buildPlatePreviewModel({ ...layout, layout_bed_mm: [0, 100, 180] }), null);
  assert.equal(buildPlatePreviewModel({ ...layout, parts: [{ ...layout.parts[0], plate_offset_mm: [190, 15, 0] }] }), null);
  assert.equal(buildPlatePreviewModel({ ...layout, parts: [{ ...layout.parts[0], extents_mm: [Number.NaN, 20, 10] }] }), null);
});
