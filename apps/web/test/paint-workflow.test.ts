import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  movePaintLayerOrder,
  paintDraftMatchesContext,
  paintLayerSummaries,
  paintStrokeBody,
  removePaintStroke,
} from "../src/lib/paint-workflow.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("paint drafts are bound to the exact immutable version and selected scene node", () => {
  assert.equal(paintDraftMatchesContext("v1", null, "v1", null), true);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v1", "chair"), true);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v2", "chair"), false);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v1", "table"), false);
  assert.equal(paintDraftMatchesContext(null, null, "v1", null), false);
});

test("draft stroke removal is immutable and bounded", () => {
  assert.deepEqual(removePaintStroke(["a", "b", "c"], 1), ["a", "c"]);
  assert.deepEqual(removePaintStroke(["a", "b"], -1), ["a", "b"]);
  assert.deepEqual(removePaintStroke(["a", "b"], 5), ["a", "b"]);
});

test("trusted material strokes never send a client-authored colour beside the catalogue id", () => {
  const region = { kind: "box", min_mm: [0, 0, 0], max_mm: [1, 1, 1] } as any;
  assert.deepEqual(
    paintStrokeBody({ colour: "#112233", catalogMaterialId: null, customTexture: null, opacity: 0.75, region: { region } as any }),
    { colour: "#112233", opacity: 0.75, region },
  );
  assert.deepEqual(
    paintStrokeBody({ colour: "#aabbcc", catalogMaterialId: "architectural.concrete", customTexture: null, opacity: 0.5, region: { region } as any }),
    { catalog_material_id: "architectural.concrete", opacity: 0.5, region },
  );
  assert.deepEqual(
    paintStrokeBody({
      colour: "#a7a7a7",
      catalogMaterialId: null,
      customTexture: { assetId: "00000000-0000-4000-8000-000000000001", tileSizeMm: 250, roughness: 0.8, metallic: 0 },
      opacity: 0.85,
      region: { region } as any,
    }),
    {
      custom_texture_asset_id: "00000000-0000-4000-8000-000000000001",
      custom_texture_tile_size_mm: 250,
      custom_texture_roughness: 0.8,
      custom_texture_metallic: 0,
      opacity: 0.85,
      region,
    },
  );
});

test("saved layer evidence rejects malformed provenance and reorders complete unique names", () => {
  const provenance = {
    paint: {
      strokes: [
        { colour: "#112233", opacity: 0.5 },
        { colour: "#445566" },
      ],
      layers: [
        { name: "Base", stroke_start: 0, stroke_count: 1 },
        { name: "Detail", stroke_start: 1, stroke_count: 1 },
      ],
    },
  };
  const layers = paintLayerSummaries(provenance);
  assert.deepEqual(layers, [
    { name: "Base", strokeCount: 1, colours: ["#112233"], materialIds: [], opacities: [0.5] },
    { name: "Detail", strokeCount: 1, colours: ["#445566"], materialIds: [], opacities: [1] },
  ]);
  assert.deepEqual(movePaintLayerOrder(layers, 0, 1), ["Detail", "Base"]);
  assert.equal(movePaintLayerOrder(layers, 0, -1), null);
  assert.deepEqual(
    paintLayerSummaries({ paint: { ...provenance.paint, strokes: [{ colour: "forged" }] } }),
    [],
  );
});

test("web studio sends named opacity layers through the exact source-bound typed routes", () => {
  assert.match(studio, /paintDraftMatchesContext\(/);
  assert.match(studio, /strokes: strokes\.map\(paintStrokeBody\)/);
  assert.match(studio, /layer_name: layerName/);
  assert.match(studio, /scene_node_id: sourceSceneNodeId/);
  assert.match(studio, /client\.reorderPaintLayers\(sourceVersionId, layerOrder, sourceSceneNodeId\)/);
  assert.match(studio, /removePaintStroke\(current, index\)/);
});

test("web studio chooses only server catalogue materials for paint strokes", () => {
  assert.match(studio, /client\.listInteriorMaterials\(\)/);
  assert.match(studio, /catalogMaterialId: paintCustomTexture \? null : paintMaterialId/);
  assert.match(studio, /paintMaterialId && !paintMaterial/);
  assert.match(studio, /paintMaterial\?\.base_color/);
});

test("web custom texture uses the existing verified upload and bounded immutable paint payload", () => {
  assert.match(studio, /client\.uploadFile\(session\.workspaceId, file, file\.name, file\.type\)/);
  assert.match(studio, /\["image\/png", "image\/jpeg"\]/);
  assert.match(studio, /file\.size > 6 \* 1024 \* 1024/);
  assert.match(studio, /customTexture: paintCustomTexture \?/);
  assert.match(studio, /tileSizeMm: customTileSizeMm/);
  assert.match(studio, /roughness: paintCustomRoughness/);
  assert.match(studio, /metallic: paintCustomMetallic/);
  assert.match(studio, /grey live stroke is only a region mask/);
});
