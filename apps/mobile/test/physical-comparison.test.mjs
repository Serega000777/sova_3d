import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sheet = readFileSync(new URL("../src/PhysicalComparisonSheet.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("F-043 mobile flow uses accepted scan versions and the typed metric job", () => {
  assert.match(sheet, /version\.provenance\?\.operation === "scan"/);
  assert.match(sheet, /comparePhysicalScan/);
  assert.match(sheet, /scale_locked/);
  assert.match(sheet, /не масштабирует сетку/);
  assert.match(project, /Сравнить с напечатанной деталью/);
  assert.match(project, /<PhysicalComparisonSheet/);
});
