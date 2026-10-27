import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 63 persists mobile point comments through revisioned plan annotations", () => {
  assert.match(project, /function postModelNote|const postModelNote/);
  assert.match(project, /makeAnnotationBase\(author\)/);
  assert.match(project, /number: nextPinNumber\(planSync\.annotations\)/);
  assert.match(project, /model_anchor_mm: point/);
  assert.match(project, /model_version_id: activeId/);
  assert.match(project, /planSync\.commit\(\[/);
});

test("saved model comments return as markers and discussion rows", () => {
  assert.match(project, /key: `annotation-\$\{annotation\.id\}`/);
  assert.match(project, /Комментарии к модели/);
  assert.match(project, /annotation\.author/);
  assert.match(project, /annotation\.note/);
});

test("projects without a floor plan persist version-scoped point comments", () => {
  assert.match(project, /\.listModelComments\(activeId\)/);
  assert.match(project, /client\.createModelComment\(activeId, text, point\)/);
  assert.match(project, /key: `model-comment-\$\{comment\.id\}`/);
  assert.match(project, /client\.updateModelComment\(/);
  assert.match(project, /comment\.revision/);
  assert.match(project, /Комментарий с выбранной 3D-точкой сохраняется для этой версии модели/);
});
