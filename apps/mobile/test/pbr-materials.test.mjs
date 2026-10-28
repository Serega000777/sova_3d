import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { interiorMaterialResultMatches } from "../src/interior-material-result.ts";

const sheet = readFileSync(new URL("../src/SceneTreeSheet.tsx", import.meta.url), "utf8");

test("scene material picker uses the immutable catalogue assignment path", () => {
  assert.match(sheet, /client\.listInteriorMaterials\(\)/);
  assert.match(sheet, /client\.assignInteriorMaterial\(sourceVersionId/);
  assert.match(sheet, /scene_node_id: sceneNodeId/);
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

test("applied PBR snapshot is bound to the exact source version and scene node", () => {
  const material = {
    id: "oak",
    name: "Oak",
    name_ru: "Дуб",
    base_color: "#a07040",
    gloss_pct: 20,
    roughness: 0.8,
    texture_sha256: "abc",
    texture_tile_size_mm: 300,
    texture_url: "/textures/abc.png",
  };
  const appearance = {
    schema_version: 1,
    catalog_material_id: material.id,
    name: material.name,
    name_ru: material.name_ru,
    base_color: material.base_color,
    gloss_pct: material.gloss_pct,
    roughness: material.roughness,
    texture_sha256: material.texture_sha256,
    texture_tile_size_mm: material.texture_tile_size_mm,
    texture_url: material.texture_url,
  };
  const scene = {
    version_id: "child",
    parent_version_id: "source",
    nodes: [{ id: "chair", kind: "object", effective_visible: true, appearance }],
  };
  assert.equal(interiorMaterialResultMatches(scene, "source", "chair", material), true);
  assert.equal(interiorMaterialResultMatches({ ...scene, parent_version_id: "other" }, "source", "chair", material), false);
  assert.equal(interiorMaterialResultMatches({ ...scene, nodes: [{ ...scene.nodes[0], id: "table" }] }, "source", "chair", material), false);
  assert.equal(interiorMaterialResultMatches({ ...scene, nodes: [{ ...scene.nodes[0], appearance: { ...appearance, roughness: 0.2 } }] }, "source", "chair", material), false);
  assert.equal(interiorMaterialResultMatches({ ...scene, nodes: [{ ...scene.nodes[0], appearance: null }] }, "source", "chair", null), true);
  assert.match(sheet, /interiorMaterialResultMatches\(next, sourceVersionId, sceneNodeId, material\)/);
});
