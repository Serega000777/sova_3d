import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/settings/page.tsx", import.meta.url), "utf8");

test("settings presents localized subscription and top-up proposals without implying billing", () => {
  assert.match(page, /client\.pricing\(\)\.catch/);
  assert.match(page, /marketPricing\.subscriptions\.map/);
  assert.match(page, /marketPricing\.credit_packs\.map/);
  assert.match(page, /Покупка и списание отключены/);
  assert.match(page, /Purchases and debits stay disabled/);
});
