import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("broken-part reconstruction sends an explicit bounded symmetry boundary", () => {
  assert.match(studio, /restore_missing_half: restoreMissingHalf \|\| null/);
  assert.match(studio, /value="x_min"/);
  assert.match(studio, /value="z_max"/);
  assert.match(studio, /Результат нужно проверить по реальной детали/);
});
