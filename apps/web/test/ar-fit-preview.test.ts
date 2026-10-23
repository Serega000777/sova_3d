import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("F-026 exports USDZ and hands it to the device AR viewer", () => {
  assert.match(page, /exportModel\(format: [^\n]+"usdz"/);
  assert.match(page, /d\.format === "usdz"/);
  assert.match(page, /rel="ar"/);
  assert.match(page, /Примерить в AR/);
  assert.match(page, /Quick Look requires an image child/);
});
