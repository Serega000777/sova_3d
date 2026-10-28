import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { removePaintStroke } from "../src/paint-draft.ts";
import { paintLayerSummaries } from "../src/paint-layers.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("mobile painting saves bounded strokes through the real immutable paint job", () => {
  assert.match(project, /client\.paintModel\(paintSourceVersionId/);
  assert.match(project, /layer_name: paintLayerName\.trim\(\)/);
  assert.match(project, /Название слоя покраски/);
  assert.match(project, /strokes: strokes\.map/);
  assert.match(project, /if \(job\.status !== "succeeded"\)/);
  assert.match(project, /await headAfterJob\(job\)/);
  assert.match(viewer, /mode === "paint" \? brushMm : undefined/);
});

test("paint result reports worker evidence and does not claim a material library", () => {
  assert.match(project, /painted_faces/);
  assert.match(project, /unused_strokes/);
  assert.match(project, /Покраска сохранена новой версией/);
  assert.match(project, /Геометрия не меняется/);
  assert.doesNotMatch(project, /Бетон|Дерево|Металл/);
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
    { name: "Body", strokeCount: 2, colours: ["#ff5533"] },
    { name: "Green compartment", strokeCount: 1, colours: ["#4caf50"] },
  ]);
  assert.deepEqual(paintLayerSummaries({ paint: { strokes: [], layers: [{ name: "Empty", stroke_start: 0, stroke_count: 1 }] } }), []);
  assert.match(project, /Сохранённые слои покраски/);
  assert.match(project, /paintLayerSummaries\(active\?\.provenance\)/);
});

test("G07 keeps the current paint-layer palette beside the live viewport", () => {
  assert.match(project, /\{mode === "paint" && \(/);
  assert.match(project, /accessibilityLabel=\{ru \? "Цвет текущего слоя покраски"/);
  assert.match(project, /key=\{`viewport-\$\{swatch\}`\}/);
  assert.match(project, /accessibilityState=\{\{ checked: colour === swatch \}\}/);
  assert.match(project, /onPress=\{\(\) => setColour\(swatch\)\}/);
  assert.match(project, /setDimensionHudVisible\(false\);[\s\S]*?setMode\(\(current\) => current === "paint"/);
});
