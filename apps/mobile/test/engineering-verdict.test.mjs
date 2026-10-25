import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { engineeringVerdictTone } from "../src/engineering-verdict.ts";

test("strength yes/no follows the load question rather than problem-check semantics", () => {
  assert.equal(engineeringVerdictTone("strength", "yes"), "positive");
  assert.equal(engineeringVerdictTone("strength", "no"), "negative");
});

test("wall and fit checks keep yes as a detected problem", () => {
  assert.equal(engineeringVerdictTone("walls", "yes"), "negative");
  assert.equal(engineeringVerdictTone("fit", "no"), "positive");
  assert.equal(engineeringVerdictTone("material", "info"), "caution");
  assert.equal(engineeringVerdictTone("overview", "unsure"), "caution");
});

test("mobile engineer card uses the intent-aware verdict tone", () => {
  const source = readFileSync(new URL("../src/EngineerCard.tsx", import.meta.url), "utf8");
  assert.match(source, /engineeringVerdictTone\(answer\.intent, answer\.verdict\)/);
  assert.match(source, /ориентировочная оценка для настольной FDM-печати/);
});
