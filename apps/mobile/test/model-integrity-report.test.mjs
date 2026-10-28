import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { integrityReportText } from "../src/model-integrity-report.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const pdf = readFileSync(new URL("../src/integrity-report-pdf.ts", import.meta.url), "utf8");

const report = {
  schemaVersion: 1,
  sourceFormat: "stl",
  targetFormat: "glb",
  printableGate: false,
  status: "warn",
  summary: "Texture evidence is unavailable",
  checks: [{ id: "watertight", status: "pass", message: "Mesh is closed", expected: true, actual: true, tolerance: null }],
  source: { format: "stl", bboxSizeMm: [10, 20, 30], faces: 12, vertices: 8, watertight: true, volumeMm3: 100, surfaceAreaMm2: 200, materialCount: null, textureCount: null, nodeCount: null, meshCount: null, animationCount: null, cameraCount: null, lightCount: null },
  output: { format: "glb", bboxSizeMm: [10, 20, 30], faces: 12, vertices: 8, watertight: true, volumeMm3: 100, surfaceAreaMm2: 200, materialCount: 0, textureCount: 0, nodeCount: 2, meshCount: 1, animationCount: 1, cameraCount: 0, lightCount: 0 },
};

test("integrity report export binds the report to stable project and version ids", () => {
  const text = integrityReportText({ report, projectName: "Bracket", projectId: "project-1", versionId: "version-2", sequenceNo: 2, language: "ru" });
  assert.match(text, /Bracket \(project-1\)/);
  assert.match(text, /v2 \(version-2\)/);
  assert.match(text, /STL → GLB/);
  assert.match(text, /10 × 20 × 30 мм/);
  assert.match(text, /Узлы сцены: 2/);
  assert.match(text, /Анимации: 1/);
  assert.match(text, /✓ Mesh is closed/);
  assert.match(text, /не расчёт прочности и не сертификация/);
});

test("mobile downloads the authorized PDF to a private cache file before native sharing", () => {
  assert.match(project, /shareIntegrityReportPdf\(client, active\.id\)/);
  assert.match(project, /Скачать PDF-отчёт/);
  assert.match(pdf, /downloadIntegrityReport\(versionId\)/);
  assert.match(pdf, /document\.type !== "application\/pdf"/);
  assert.match(pdf, /new File\(Paths\.cache, `sova-integrity-\$\{versionId\}\.pdf`\)/);
  assert.match(pdf, /shareAsync\(file\.uri/);
});

test("mobile offers report sharing only after a parsed report exists", () => {
  assert.match(project, /\{activeModelCheck && project && active && \(/);
  assert.match(project, /integrityReportText\(\{/);
  assert.match(project, /Share\.share\(\{ message \}\)/);
});

test("mobile restores the persisted report for the exact selected version", () => {
  assert.match(project, /getLatestIntegrityReport\(activeId\)/);
  assert.match(project, /parseOrdinaryModelCheck\(record\.report\)/);
  assert.match(project, /reason instanceof ApiError/);
  assert.match(project, /reason\.status !== 404/);
});
