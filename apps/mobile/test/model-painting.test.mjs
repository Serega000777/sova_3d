import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { removePaintStroke } from "../src/paint-draft.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("mobile painting saves bounded strokes through the real immutable paint job", () => {
  assert.match(project, /client\.paintModel\(paintSourceVersionId/);
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
