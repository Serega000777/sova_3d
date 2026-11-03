import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { removePaintStroke } from "../src/paint-draft.ts";
import { movePaintLayerOrder, paintLayerSummaries } from "../src/paint-layers.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("mobile painting saves bounded strokes through the real immutable paint job", () => {
  assert.match(project, /client\.paintModel\(paintSourceVersionId/);
  assert.match(project, /layer_name: paintLayerName\.trim\(\)/);
  assert.match(project, /opacity: stroke\.opacity/);
  assert.match(project, /Название слоя покраски/);
  assert.match(project, /strokes: strokes\.map/);
  assert.match(project, /if \(job\.status !== "succeeded"\)/);
  assert.match(project, /await headAfterJob\(job\)/);
  assert.match(viewer, /mode === "paint" \? brushMm : undefined/);
});

test("paint result reports worker evidence and exposes only trusted concrete wood metal materials", () => {
  assert.match(project, /painted_faces/);
  assert.match(project, /unused_strokes/);
  assert.match(project, /materials\?: string\[\]/);
  assert.match(project, /Покраска сохранена новой версией/);
  assert.match(project, /Геометрия не меняется/);
  assert.match(project, /PAINT_MATERIAL_KINDS = new Set\(\["concrete", "wood", "metal"\]\)/);
  assert.match(project, /catalog_material_id: stroke\.catalogMaterialId/);
  assert.match(project, /item\.roughness/);
  assert.match(project, /item\.metallic/);
});

test("paint draft is source-version bound and individual strokes can be removed", () => {
  assert.deepEqual(removePaintStroke(["a", "b", "c"], 1), ["a", "c"]);
  assert.deepEqual(removePaintStroke(["a"], -1), ["a"]);
  assert.deepEqual(removePaintStroke(["a"], 2), ["a"]);
  assert.match(project, /paintSourceVersionId !== active\.id/);
  assert.match(project, /client\.paintModel\(paintSourceVersionId/);
  assert.match(project, /setPaintSourceVersionId\(null\)/);
  assert.match(project, /Штрихи текущего слоя/);
  assert.match(project, /Удалить штрих/);
  assert.match(project, /Отменить последний/);
});

test("saved paint layers come only from valid immutable provenance ranges", () => {
  assert.deepEqual(paintLayerSummaries({
    paint: {
      strokes: [
        { colour: "#ff5533" },
        { colour: "#ff5533" },
        { colour: "#4caf50" },
      ],
      layers: [
        { name: "Body", stroke_start: 0, stroke_count: 2 },
        { name: "Green compartment", stroke_start: 2, stroke_count: 1 },
        { name: "Forged", stroke_start: 3, stroke_count: 2 },
      ],
    },
  }), [
    { name: "Body", strokeCount: 2, colours: ["#ff5533"], materialIds: [], opacities: [1] },
    { name: "Green compartment", strokeCount: 1, colours: ["#4caf50"], materialIds: [], opacities: [1] },
  ]);
  assert.deepEqual(paintLayerSummaries({ paint: { strokes: [], layers: [{ name: "Empty", stroke_start: 0, stroke_count: 1 }] } }), []);
  assert.deepEqual(paintLayerSummaries({
    paint: {
      strokes: [{ colour: "#ff5533", opacity: 0.85 }],
      layers: [{ name: "Soft", stroke_start: 0, stroke_count: 1 }],
    },
  }), [{ name: "Soft", strokeCount: 1, colours: ["#ff5533"], materialIds: [], opacities: [0.85] }]);
  assert.deepEqual(paintLayerSummaries({
    paint: {
      strokes: [{ catalog_material_id: "interior.wood.oak-natural.v1", opacity: 1 }],
      layers: [{ name: "Oak", stroke_start: 0, stroke_count: 1 }],
    },
  }), [{ name: "Oak", strokeCount: 1, colours: [], materialIds: ["interior.wood.oak-natural.v1"], opacities: [1] }]);
  assert.deepEqual(paintLayerSummaries({
    paint: {
      strokes: [{ colour: "#ff5533", opacity: 2 }],
      layers: [{ name: "Forged opacity", stroke_start: 0, stroke_count: 1 }],
    },
  }), []);
  assert.deepEqual(paintLayerSummaries({
    paint: {
      strokes: [{ catalog_material_id: "interior.wood.oak-natural.v1", opacity: 0.85 }],
      layers: [{ name: "Oak wash", stroke_start: 0, stroke_count: 1 }],
    },
  }), [{ name: "Oak wash", strokeCount: 1, colours: [], materialIds: ["interior.wood.oak-natural.v1"], opacities: [0.85] }]);
  assert.deepEqual(paintLayerSummaries({
    scene_paint: {
      part_a: {
        strokes: [{ colour: "#1188ff", opacity: 0.75 }],
        layers: [{ name: "Node accent", stroke_start: 0, stroke_count: 1 }],
      },
    },
  }, "part_a"), [{ name: "Node accent", strokeCount: 1, colours: ["#1188ff"], materialIds: [], opacities: [0.75] }]);
  assert.match(project, /Сохранённые слои покраски/);
  assert.match(project, /paintLayerSummaries\(\s*active\?\.provenance/);
});

test("saved layers can be moved only as one complete unique order", () => {
  const layers = [
    { name: "Base", strokeCount: 1, colours: ["#000000"], materialIds: [], opacities: [1] },
    { name: "Accent", strokeCount: 1, colours: ["#ffffff"], materialIds: [], opacities: [0.85] },
  ];
  assert.deepEqual(movePaintLayerOrder(layers, 0, 1), ["Accent", "Base"]);
  assert.equal(movePaintLayerOrder(layers, 0, -1), null);
  assert.equal(movePaintLayerOrder([layers[0], layers[0]], 0, 1), null);
  assert.match(project, /client\.reorderPaintLayers\(\s*active\.id,\s*layerOrder/);
  assert.match(project, /await headAfterJob\(job\)/);
  assert.match(project, /Порядок: нижний → верхний/);
  assert.match(project, /Опустить слой/);
  assert.match(project, /Поднять слой/);
});

test("brush opacity is explicit, source-bound, and visible in the live trail", () => {
  assert.match(project, /const PAINT_OPACITIES = \[0\.5, 0\.75, 0\.85, 1\]/);
  assert.match(project, /Непрозрачность кисти/);
  assert.match(project, /opacity: paintOpacity/);
  assert.match(project, /paintOpacity=\{paintOpacity\}/);
  assert.match(project, /catalogMaterialId: paintMaterialId, opacity: paintOpacity/);
  assert.match(project, /запекается в непрозрачную PBR-поверхность/);
  assert.match(viewer, /material\.opacity = mode === "paint" \? paintOpacity : 1/);
});

test("multi-object painting is bound to one selected direct scene node", () => {
  assert.match(project, /paintSourceSceneNodeId/);
  assert.match(project, /scene_node_id: selectedSceneNodeId/);
  assert.match(project, /selectedSceneNode\.instance_of !== null/);
  assert.match(project, /selectedSceneNodePaintable/);
  assert.match(project, /paintLayerSummaries\(\s*active\?\.provenance,\s*hasExplicitScene \? selectedSceneNodeId : null/);
  assert.match(project, /reorderPaintLayers\([\s\S]*?hasExplicitScene \? selectedSceneNodeId : null/);
  assert.match(project, /if \(hasExplicitScene && \(!selectedSceneNodeId \|\| !selectedSceneNodePaintable\)\) return/);
  assert.doesNotMatch(project, /busy \|\| hasExplicitScene \|\| strokes\.length/);
});

test("G07 keeps the current paint-layer palette beside the live viewport", () => {
  assert.match(project, /\{mode === "paint" && \(/);
  assert.match(project, /accessibilityLabel=\{ru \? "Цвет текущего слоя покраски"/);
  assert.match(project, /key=\{`viewport-\$\{swatch\}`\}/);
  assert.match(project, /accessibilityState=\{\{ checked: !paintMaterialId && colour === swatch \}\}/);
  assert.match(project, /setColour\(swatch\);[\s\S]*?setPaintMaterialId\(null\)/);
  assert.match(project, /setDimensionHudVisible\(false\);[\s\S]*?setMode\(\(current\) => current === "paint"/);
});
