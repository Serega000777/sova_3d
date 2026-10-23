import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const card = readFileSync(new URL("../src/components/FitTestCard.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("a measured non-colliding fit can be saved through the canonical scene path", () => {
  assert.match(card, /fit_test_id/);
  assert.match(card, /measured\.verdict !== "collides"/);
  assert.match(card, /onCreateAssembly\(fitTestId\)/);
  assert.match(project, /client\.createFitAssembly\(fitTestId\)/);
  assert.match(project, /client\.getVersion\(made\.version_id\)/);
});
