import assert from "node:assert/strict";
import test from "node:test";

import { buildPlatePreviewModel, verifiedBuildPlateLayout } from "../src/build-plate-preview.ts";

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
  assert.equal(buildPlatePreviewModel({ ...layout, parts: [{ ...layout.parts[0], extents_mm: [40, 20, 181] }] }), null);
});

const split = {
  ...layout,
  request: { bed: { x_mm: 200, y_mm: 100, z_mm: 180 }, margin_mm: 5, gap_mm: 8 },
  layout_extents_mm: [120, 60, 10],
  minimum_edge_clearance_mm: 5,
  minimum_part_clearance_mm: 8,
  warnings: [],
  repaired: null,
  planes: [],
  parts: [{ ...layout.parts[0], asset_id: "part-asset", volume_mm3: 8000, cut_faces: 1, dowel_holes: 0, fits_bed: true, edge_clearance_mm: 5, nearest_clearance_mm: 8 }],
  dowels: [{ ...layout.dowels[0], asset_id: "dowel-asset", length_mm: 12, edge_clearance_mm: 40, nearest_clearance_mm: 8 }],
};

const draft = {
  state: "draft",
  parent_version_id: "source-94",
  provenance: { operation: "split_model", source_version_id: "source-94", split },
};

test("reference 94 accepts only the exact source-bound fit-to-bed draft", () => {
  assert.equal(verifiedBuildPlateLayout(draft, "source-94", 5, 8), split);
  assert.equal(verifiedBuildPlateLayout({ ...draft, state: "finalized" }, "source-94", 5, 8), null);
  assert.equal(verifiedBuildPlateLayout(draft, "other-source", 5, 8), null);
  assert.equal(verifiedBuildPlateLayout({ ...draft, provenance: { ...draft.provenance, split: { ...split, minimum_edge_clearance_mm: 4.9 } } }, "source-94", 5, 8), null);
  assert.equal(verifiedBuildPlateLayout({ ...draft, provenance: { ...draft.provenance, split: { ...split, minimum_part_clearance_mm: 7.9 } } }, "source-94", 5, 8), null);
});
