import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const passport = readFileSync(new URL("../src/ModelPassportSheet.tsx", import.meta.url), "utf8");

test("the selected immutable version opens a canonical model passport", () => {
  assert.match(project, /setModelPassportOpen\(true\)/);
  assert.match(project, /project=\{project\}/);
  assert.match(project, /version=\{active\}/);
  assert.match(project, /history=\{activeHistory\}/);
  assert.match(project, /report=\{modelCheck\}/);
  assert.match(project, /onShareIntegrityPdf=\{\(\) => void downloadIntegrityPdf\(\)\}/);
  assert.match(passport, /version\.sequence_no/);
  assert.match(passport, /history\?\.creator_name/);
  assert.match(passport, /version\.assets\.length/);
});

test("the passport never invents a passed check or exact CAD export", () => {
  assert.match(passport, /!report\s*\?\s*"not_checked"/);
  assert.match(passport, /паспорт не подменяет её зелёным статусом/);
  assert.match(passport, /STEP и IGES доступны только версиям с точной CAD-геометрией/);
  assert.match(passport, /STL, 3MF, GLB, FBX и USDZ/);
  assert.match(passport, /onOpenCheck/);
  assert.match(project, /setModelCheck\(null\);[\s\S]*?\}, \[activeId\]\);/);
});

test("sharing contains stable project and version identifiers", () => {
  assert.match(passport, /Share\.share\(\{ message: modelPassportText\(data, language\) \}\)/);
  assert.match(passport, /data\.projectId/);
  assert.match(passport, /data\.versionId/);
  assert.match(passport, /data\.sequenceNo/);
  assert.match(passport, /data\.integrity/);
});

test("a checked passport exposes the exact version-bound PDF without calling it a certificate", () => {
  assert.match(passport, /\{report && \(/);
  assert.match(passport, /onPress=\{onShareIntegrityPdf\}/);
  assert.match(passport, /Поделиться PDF проверки/);
  assert.match(passport, /Это не цифровая подпись и не публичный сертификат/);
  assert.match(project, /shareIntegrityReportPdf\(client, active\.id\)/);
});
