import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("mobile painting saves bounded strokes through the real immutable paint job", () => {
  assert.match(project, /client\.paintModel\(active\.id/);
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
