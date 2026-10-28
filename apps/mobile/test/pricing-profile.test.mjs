import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const profile = readFileSync(new URL("../app/(tabs)/profile.tsx", import.meta.url), "utf8");

test("mobile profile shows the Russian pricing proposal and degrades if pricing is unavailable", () => {
  assert.match(profile, /client\.pricing\(\)\.catch/);
  assert.match(profile, /marketPricing\.subscriptions\.map/);
  assert.match(profile, /marketPricing\.credit_packs\.map/);
  assert.match(profile, /Покупка и списание отключены/);
});
