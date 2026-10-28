import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/cart/page.tsx", import.meta.url), "utf8");

test("M09 renders live cart totals per currency without inventing conversion", () => {
  assert.match(page, /cart\.totals\.map/);
  assert.match(page, /total\.amount_cents/);
  assert.match(page, /total\.currency/);
  assert.doesNotMatch(page, /total_cents \?\? 0/);
  assert.doesNotMatch(page, /toFixed\(2\)} USD/);
  assert.match(page, /Платёжный провайдер ещё не выбран/);
});
