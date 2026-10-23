import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../src/app/scanner/[id]/page.tsx", import.meta.url),
  "utf8",
);

test("RoomPlan results expose honest measured print ideas and a real template build path", () => {
  assert.match(source, /client\.getScanPrintIdeas\(current\.id\)/);
  assert.match(source, /not object recognition/);
  assert.match(source, /не на распознавании предметов/);
  assert.match(source, /client\.startFromTemplate/);
  assert.match(source, /params: idea\.params/);
  assert.match(source, /client\.waitForJob\(started\.job\.job_id\)/);
});
