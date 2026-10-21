import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 51 runs the existing non-mutating integrity pipeline", () => {
  assert.match(project, /async function checkModel\(\)/);
  assert.match(project, /client\.exportModel\(active\.id, \{[\s\S]*format: "glb",[\s\S]*printable: false/);
  assert.match(project, /job\.status === "succeeded" \? result\?\.report : failure\?\.details\?\.report/);
  assert.match(project, /parseIntegrityReport/);
  assert.match(project, /Модель не изменяется/);
});

test("model check never turns absent appearance evidence into a green claim", () => {
  assert.match(project, /appearanceCheckStatus === "unknown"/);
  assert.match(project, /Формат источника не содержит проверяемых данных/);
  assert.match(project, /Готова с замечаниями/);
  assert.match(project, /Проверить ещё раз/);
});

test("model check reports geometry, appearance and metric dimensions separately", () => {
  assert.match(project, /label: ru \? "Геометрия"/);
  assert.match(project, /label: ru \? "Материалы и текстуры"/);
  assert.match(project, /label: ru \? "Масштаб"/);
  assert.match(project, /modelCheck\.output\.bboxSizeMm/);
});
