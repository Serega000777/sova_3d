import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/ScannedFacadeSheet.tsx", import.meta.url), "utf8");

test("reference 19 turns an exterior scan into an exact semantic facade", () => {
  assert.match(project, /report\?\.provider\s*\n\s*=== "colmap_exterior"/);
  assert.match(project, /client\.createFacadeFromScan/);
  assert.match(project, /Построить фасад по скану/);
  assert.match(sheet, /Введите измеренные размеры и проёмы/);
  assert.match(sheet, /addOpening\("window"\)/);
  assert.match(sheet, /addOpening\("door"\)/);
  assert.match(sheet, /wall_colour: colour/);
  assert.match(sheet, /Создать точный фасад/);
});
