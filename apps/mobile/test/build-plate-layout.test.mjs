import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 94 runs the typed printer-aware split and nesting job as a draft", () => {
  assert.match(project, /client\.splitModel\(active\.id/);
  assert.match(project, /fit_bed: true/);
  assert.match(project, /printer_profile_id: printProfileId/);
  assert.match(project, /margin_mm: 5/);
  assert.match(project, /gap_mm: 8/);
  assert.match(project, /preview: true/);
});

test("mobile reports measured placement facts before explicit keep or discard", () => {
  assert.match(project, /<BuildPlatePreview layout=\{layout\}/);
  assert.match(project, /layout\.minimum_edge_clearance_mm/);
  assert.match(project, /layout\.minimum_part_clearance_mm/);
  assert.match(project, /part\.plate_offset_mm\[0\]/);
  assert.match(project, /part\.plate_rotation_deg/);
  assert.match(project, /client\.acceptVersion\(plateLayoutDraft\.id\)/);
  assert.match(project, /client\.discardVersion\(plateLayoutDraft\.id\)/);
});
