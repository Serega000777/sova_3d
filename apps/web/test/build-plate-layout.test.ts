import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { Version } from "@physical-ai/contracts";

import { verifiedWebBuildPlateLayout } from "../src/lib/build-plate-layout.ts";

const slicer = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");

function draft(): Version {
  return {
    id: "draft-version",
    project_id: "project-1",
    parent_version_id: "source-version",
    sequence_no: 2,
    state: "draft",
    label: "Build plate layout",
    created_by: "user-1",
    created_at: "2026-11-21T00:00:00Z",
    assets: [],
    provenance: {
      operation: "split_model",
      source_version_id: "source-version",
      split: {
        request: {
          bed: { x_mm: 220, y_mm: 220, z_mm: 250 },
          margin_mm: 5,
          gap_mm: 8,
        },
        planes: [],
        parts: [{
          name: "part-1.stl",
          asset_id: "asset-1",
          extents_mm: [100, 80, 40],
          volume_mm3: 10,
          cut_faces: 0,
          dowel_holes: 0,
          fits_bed: true,
          plate_offset_mm: [5, 5, 0],
          plate_rotation_deg: 0,
          edge_clearance_mm: 5,
          nearest_clearance_mm: null,
        }],
        dowels: [],
        layout_extents_mm: [105, 85, 40],
        layout_bed_mm: [220, 220, 250],
        minimum_edge_clearance_mm: 5,
        minimum_part_clearance_mm: null,
        warnings: [],
        repaired: null,
      },
    },
  } as Version;
}

test("reference 94 accepts only the exact source-bound fit-to-bed draft", () => {
  assert.ok(verifiedWebBuildPlateLayout(draft(), "source-version", 5, 8));
  assert.equal(verifiedWebBuildPlateLayout(draft(), "another-source", 5, 8), null);
  const finalized = structuredClone(draft());
  finalized.state = "finalized";
  assert.equal(verifiedWebBuildPlateLayout(finalized, "source-version", 5, 8), null);
});

test("reference 94 rejects forged clearances and out-of-bed geometry", () => {
  const forged = structuredClone(draft());
  const split = (forged.provenance as any).split;
  split.minimum_edge_clearance_mm = 4.9;
  assert.equal(verifiedWebBuildPlateLayout(forged, "source-version", 5, 8), null);

  const outside = structuredClone(draft());
  (outside.provenance as any).split.parts[0].plate_offset_mm = [150, 5, 0];
  assert.equal(verifiedWebBuildPlateLayout(outside, "source-version", 5, 8), null);
});

test("reference 94 rejects duplicate names and missing stored assets", () => {
  const duplicate = structuredClone(draft());
  const split = (duplicate.provenance as any).split;
  split.dowels.push({
    name: "part-1.stl",
    asset_id: "asset-2",
    diameter_mm: 5,
    length_mm: 12,
    plate_offset_mm: [120, 5, 0],
    edge_clearance_mm: 5,
    nearest_clearance_mm: 15,
  });
  split.minimum_part_clearance_mm = 15;
  assert.equal(verifiedWebBuildPlateLayout(duplicate, "source-version", 5, 8), null);

  const missing = structuredClone(draft());
  (missing.provenance as any).split.parts[0].asset_id = "";
  assert.equal(verifiedWebBuildPlateLayout(missing, "source-version", 5, 8), null);
});

test("reference 94 keeps the web result as a verified draft until an explicit decision", () => {
  const cutFlow = slicer.slice(
    slicer.indexOf("async function cut"),
    slicer.indexOf("async function exportFor"),
  );
  assert.match(cutFlow, /preview: true/);
  assert.match(cutFlow, /client\.getVersion\(draftVersionId\)/);
  assert.match(cutFlow, /verifiedWebBuildPlateLayout/);
  assert.match(cutFlow, /client\.acceptVersion\(draft\.version\.id\)/);
  assert.match(cutFlow, /client\.discardVersion\(draft\.version\.id\)/);
  assert.doesNotMatch(cutFlow, /setVersionId\(result\.version_id\)/);
  assert.match(slicer, /Сохранить раскладку/);
  assert.match(slicer, /Удалить черновик/);
});
