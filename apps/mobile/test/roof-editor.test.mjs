import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/RoofEditorSheet.tsx", import.meta.url), "utf8");

test("mobile roof builder reaches the immutable exact facade job", () => {
  assert.match(project, /client\.editFacade\(active\.id, request\)/);
  assert.match(project, /Конструктор крыши/);
  assert.match(sheet, /\["gable", "flat", "hip"\]/);
  assert.match(sheet, /Уклон скатов, °/);
  assert.match(sheet, /roof_height_mm: heightMm/);
  assert.match(sheet, /overhang_mm: overhangMm/);
});
