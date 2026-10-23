import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");

test("print-farm planning exposes a bounded multi-model multi-printer workflow", () => {
  assert.match(page, /Партия для нескольких принтеров/);
  assert.match(page, /batchQuantities/);
  assert.match(page, /batchPrinterIds/);
  assert.match(page, /client\.planPrintFarm/);
  assert.match(page, /batchPlan\.assignments\.map/);
  assert.match(page, /физическая отправка на принтеры выполняется отдельно/);
});
