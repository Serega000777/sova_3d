import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("calibrated photo measurements reach a real CAD build without vision claims", () => {
  const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");
  assert.match(client, /proposeFunctionalPart/);
  assert.match(studio, /client\.proposeFunctionalPart/);
  assert.match(studio, /client\.createDimensionedDrawing/);
  assert.match(studio, /Содержимое фото не распознаётся/);
  assert.match(studio, /referenceSync !== "synced"/);
});
