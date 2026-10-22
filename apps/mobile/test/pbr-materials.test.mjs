import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sheet = readFileSync(new URL("../src/SceneTreeSheet.tsx", import.meta.url), "utf8");

test("scene material picker uses the immutable catalogue assignment path", () => {
  assert.match(sheet, /client\.listInteriorMaterials\(\)/);
  assert.match(sheet, /client\.assignInteriorMaterial\(versionId/);
  assert.match(sheet, /scene_node_id: current\.id/);
  assert.match(sheet, /await onSaved\(next\.version_id\)/);
});

test("applied PBR result reports canonical parameters without fake editable sliders", () => {
  assert.match(sheet, /current\.appearance\.base_color/);
  assert.match(sheet, /current\.appearance\.roughness/);
  assert.match(sheet, /current\.appearance\.gloss_pct/);
  assert.match(sheet, /current\.appearance\.texture_sha256/);
  assert.match(sheet, /current\.appearance\.texture_tile_size_mm/);
  assert.match(sheet, /металличность.*0%/s);
  assert.match(sheet, /accessibilityState=\{\{ selected: current\.appearance\?\.catalog_material_id === item\.id/);
  assert.doesNotMatch(sheet, /setRoughness|setMetalness|metallicFactor/);
});
