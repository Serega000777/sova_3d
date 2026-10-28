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
  assert.match(project, /report=\{activeModelCheck\}/);
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
  assert.match(project, /const activeModelCheck = modelCheckVersionId === activeId \? modelCheck : null/);
  assert.match(project, /setModelCheckVersionId\(activeId\)/);
  assert.match(project, /setModelCheckVersionId\(active\.id\)/);
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

test("alternate reference 97/02 adds only canonical description, bytes and measured triangles", () => {
  assert.match(passport, /project\.description\?\.trim\(\) \|\| null/);
  assert.match(passport, /history\.total_asset_bytes/);
  assert.match(passport, /report\?\.output\.faces/);
  assert.match(passport, /positiveInteger\(report\?\.output\.faces\)/);
  assert.match(passport, /Number\.isInteger\(value\)/);
  assert.match(passport, /Размер сохранённых файлов/);
  assert.match(passport, /Измеренных треугольников/);
  assert.doesNotMatch(passport, /rating|рейтинг|Готова к рендеру/);
});
