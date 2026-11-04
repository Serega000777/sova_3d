import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/collections/page.tsx", import.meta.url), "utf8");
const library = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");

test("reference 100 web library reads only canonical favorites and completed orders", () => {
  assert.match(page, /client\.favoriteListings\(\)/);
  assert.match(page, /client\.myOrders\(\)/);
  assert.match(page, /nextOrders\.filter\(\(order\) => order\.status === "completed"\)/);
  assert.match(page, /client\.orderFiles\(order\.id\)/);
  assert.match(page, /loadRevision\.current !== request/);
  assert.match(library, /href="\/collections"/);
});

test("delivered downloads are rebound to exact buyer-authorized file evidence", () => {
  assert.match(page, /client\.download\(file\.asset_id\)/);
  assert.match(page, /verifiedMarketplaceDownloadUrl\(file, download\)/);
  assert.match(page, /window\.open\(url, "_blank", "noopener"\)/);
  assert.match(page, /client\.downloadOrderSovaPackage\(order\.id\)/);
  assert.match(page, /order\.project_id && \(/);
});

test("one order file failure remains local instead of hiding purchases", () => {
  assert.match(page, /files: \[\] as MarketplaceFile\[\]/);
  assert.match(page, /setFileErrors/);
  assert.match(page, /fileErrors\[order\.id\]/);
  assert.match(page, /Файлы заказа временно недоступны/);
});

test("web library does not claim manufacturing or device download history", () => {
  assert.match(page, /не является очередью физического производства/);
  assert.doesNotMatch(page, /Заказать печать|Доставим за|Скачано на устройство/);
});
