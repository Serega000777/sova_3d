import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { interiorMaterialResultMatches } from "../src/lib/interior-material.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("web studio applies the catalogue swatch through the immutable assignment route", () => {
  assert.match(studio, /client\.listInteriorMaterials\(\)/);
  assert.match(studio, /client\.assignInteriorMaterial\(sourceVersionId/);
  assert.match(studio, /scene_node_id: sceneNodeId/);
  assert.match(studio, /catalog_material_id: materialId/);
});

test("web studio verifies the returned material is bound to the exact source version and node before committing it", () => {
  assert.match(studio, /interiorMaterialResultMatches\(made, sourceVersionId, sceneNodeId, material\)/);
  assert.match(
    studio,
    /activeVersionId !== sourceVersionId \|\| selected\.length !== 1 \|\| selected\[0\] !== sceneNodeId/,
  );
});

test("web studio shows canonical applied-material evidence instead of editable sliders", () => {
  assert.match(studio, /selectedInteriorAppearance\.base_color/);
  assert.match(studio, /selectedInteriorAppearance\.roughness/);
  assert.match(studio, /selectedInteriorAppearance\.gloss_pct/);
  assert.match(studio, /selectedInteriorAppearance\.texture_sha256/);
  assert.match(studio, /selectedInteriorAppearance\.texture_tile_size_mm/);
  assert.match(studio, /selectedInteriorAppearance\.metallic/);
  assert.doesNotMatch(studio, /setRoughness|setMetalness|metallicFactor/);
});

test("applied PBR snapshot is bound to the exact source version and scene node", () => {
  const material = {
    id: "oak",
    name: "Oak",
    name_ru: "Дуб",
    base_color: "#a07040",
    gloss_pct: 20,
    roughness: 0.8,
    metallic: 0,
    texture_sha256: "abc",
    texture_tile_size_mm: 300,
    texture_url: "/textures/abc.png",
  };
  const appearance = {
    schema_version: 1 as const,
    catalog_material_id: material.id,
    name: material.name,
    name_ru: material.name_ru,
    base_color: material.base_color,
    gloss_pct: material.gloss_pct,
    roughness: material.roughness,
    metallic: material.metallic,
    texture_sha256: material.texture_sha256,
    texture_tile_size_mm: material.texture_tile_size_mm,
    texture_url: material.texture_url,
  };
  const scene = {
    version_id: "child",
    parent_version_id: "source",
    nodes: [{ id: "chair", kind: "object" as const, effective_visible: true, appearance }],
  };
  assert.equal(interiorMaterialResultMatches(scene as any, "source", "chair", material), true);
  assert.equal(
    interiorMaterialResultMatches({ ...scene, parent_version_id: "other" } as any, "source", "chair", material),
    false,
  );
  assert.equal(
    interiorMaterialResultMatches(
      { ...scene, nodes: [{ ...scene.nodes[0], id: "table" }] } as any,
      "source",
      "chair",
      material,
    ),
    false,
  );
  assert.equal(
    interiorMaterialResultMatches(
      { ...scene, nodes: [{ ...scene.nodes[0], appearance: { ...appearance, roughness: 0.2 } }] } as any,
      "source",
      "chair",
      material,
    ),
    false,
  );
  assert.equal(
    interiorMaterialResultMatches(
      { ...scene, nodes: [{ ...scene.nodes[0], appearance: null }] } as any,
      "source",
      "chair",
      null,
    ),
    true,
  );
  assert.equal(
    interiorMaterialResultMatches({ ...scene, version_id: "source" } as any, "source", "chair", material),
    false,
  );
  const otherNode = { id: "table", kind: "object" as const, effective_visible: true, appearance: null };
  assert.equal(
    interiorMaterialResultMatches(
      { ...scene, nodes: [scene.nodes[0], otherNode] } as any,
      "source",
      "table",
      null,
    ),
    true,
  );
});
