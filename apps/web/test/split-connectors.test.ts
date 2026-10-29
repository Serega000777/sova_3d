import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const splitCard = readFileSync(
  new URL("../src/components/SplitCard.tsx", import.meta.url),
  "utf8",
);

test("split card exposes a bounded dowel count and sends it per cut", () => {
  assert.match(splitCard, /aria-label="Dowels per cut"/);
  assert.match(splitCard, /min=\{1\}/);
  assert.match(splitCard, /max=\{8\}/);
  assert.match(splitCard, /disabled=\{!dowels\}/);
  assert.match(splitCard, /count_per_cut: dowelCount/);
});
