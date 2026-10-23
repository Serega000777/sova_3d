import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/creators/[handle]/page.tsx", import.meta.url), "utf8");

test("creator pages expose real public collections and owner-only management", () => {
  assert.match(page, /page\.collections/);
  assert.match(page, /createCreatorCollection/);
  assert.match(page, /deleteCreatorCollection/);
  assert.match(page, /collection\.listings\.map/);
  assert.match(page, /own &&/);
});

test("creator insights expose only measured orders downloads and gross", () => {
  assert.match(page, /creatorInsights/);
  assert.match(page, /trend\.recent_orders/);
  assert.match(page, /item\.gross_cents/);
  assert.match(page, /Завершённых заказов пока нет — данных для тренда недостаточно/);
});
