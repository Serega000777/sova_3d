import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sheet = readFileSync(new URL("../src/PhysicalComparisonSheet.tsx", import.meta.url), "utf8");

test("post-print comparison can update only bounded XY shrinkage on a chosen printer", () => {
  assert.match(sheet, /listPrinterProfiles/);
  assert.match(sheet, /calibratePrinterFromComparison/);
  assert.match(sheet, /Применяется только безопасная равномерная поправка усадки X\/Y/);
  assert.match(sheet, /Отверстия, поток, температура и ось Z не меняются/);
});
