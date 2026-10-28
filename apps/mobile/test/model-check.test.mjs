import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseOrdinaryModelCheck, verifiedModelCheckJob } from "../src/model-check.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 51 runs the existing non-mutating integrity pipeline", () => {
  assert.match(project, /async function checkModel\(\)/);
  assert.match(project, /client\.exportModel\(active\.id, \{[\s\S]*format: "glb",[\s\S]*printable: false/);
  assert.match(project, /verifiedModelCheckJob\(job, active\.id\)/);
  assert.match(project, /Модель не изменяется/);
});

const geometry = (format) => ({
  format,
  bbox_size_mm: [10, 20, 30],
  faces: 12,
  vertices: 8,
  watertight: true,
  volume_mm3: 6000,
  surface_area_mm2: 2200,
  material_count: 0,
  texture_count: 0,
  node_count: 1,
  mesh_count: 1,
  animation_count: 0,
  camera_count: 0,
  light_count: 0,
});

const report = (overrides = {}) => ({
  schema_version: 1,
  source_format: "stl",
  target_format: "glb",
  printable_gate: false,
  status: "pass",
  checks: [],
  summary: "verified",
  source: geometry("stl"),
  output: geometry("glb"),
  ...overrides,
});

const job = (overrides = {}) => ({
  type: "export",
  status: "succeeded",
  project_version_id: "version-90",
  result: { format: "glb", printable_gate: false, report: report() },
  error: null,
  ...overrides,
});

test("reference 90 accepts only the exact version-bound ordinary GLB check", () => {
  assert.equal(verifiedModelCheckJob(job(), "version-90")?.targetFormat, "glb");
  assert.equal(verifiedModelCheckJob(job(), "other-version"), null);
  assert.equal(verifiedModelCheckJob(job({ type: "game_export" }), "version-90"), null);
  assert.equal(verifiedModelCheckJob(job({ result: { format: "glb", printable_gate: true, report: report({ printable_gate: true }) } }), "version-90"), null);
  assert.equal(parseOrdinaryModelCheck(report({ target_format: "obj", output: geometry("obj") })), null);
  assert.equal(verifiedModelCheckJob(job({ status: "succeeded", result: { format: "glb", printable_gate: false, report: report({ status: "fail" }) } }), "version-90"), null);
  assert.equal(
    verifiedModelCheckJob(job({ status: "failed", result: null, error: { details: { report: report({ status: "fail" }) } } }), "version-90")?.status,
    "fail",
  );
  assert.match(project, /parseOrdinaryModelCheck\(record\.report\)/);
});

test("model check never turns absent appearance evidence into a green claim", () => {
  assert.match(project, /appearanceCheckStatus === "unknown"/);
  assert.match(project, /Формат источника не содержит проверяемых данных/);
  assert.match(project, /Готова с замечаниями/);
  assert.match(project, /Проверить ещё раз/);
});

test("model check reports geometry, scene, appearance and metric dimensions separately", () => {
  assert.match(project, /label: ru \? "Геометрия"/);
  assert.match(project, /label: ru \? "Структура сцены"/);
  assert.match(project, /"scene_node_count"/);
  assert.match(project, /activeModelCheck\.output\.animationCount/);
  assert.match(project, /label: ru \? "Материалы и текстуры"/);
  assert.match(project, /label: ru \? "Масштаб"/);
  assert.match(project, /activeModelCheck\.output\.bboxSizeMm/);
});

test("G08 shows only the progress actually reported by the server job", () => {
  assert.match(project, /busy\?\.startsWith\(label\)/);
  assert.match(project, /busy\.match\(\/ · \(\\d\+\)%\$\//);
  assert.match(project, /accessibilityLabel=\{ru \? "Ход серверной проверки модели"/);
  assert.match(project, /width: `\$\{modelCheckProgress\.progress\}%`/);
  assert.match(project, /Процент сообщает job; отдельные этапы проверки появятся только если их начнёт отдавать сервер/);
  assert.doesNotMatch(project, /setCheckStage|checkStage/);
});
