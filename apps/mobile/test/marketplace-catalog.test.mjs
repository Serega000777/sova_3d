import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/(tabs)/market.tsx", import.meta.url), "utf8");
const detail = readFileSync(new URL("../app/market/[id].tsx", import.meta.url), "utf8");

test("alternate reference 51/02 shows only canonical saved listing thumbnails", () => {
  assert.match(source, /listing\.thumbnail_asset_id/);
  assert.match(source, /client\.download\(listing\.thumbnail_asset_id\)/);
  assert.match(source, /thumbnailUrls\[listing\.id\]/);
  assert.match(source, /<Image/);
  assert.doesNotMatch(source, /versionThumbnailUrl|ensureVersionThumbnail|createThumbnail/);
});

test("alternate reference 51/03 opens a read-only listing card before acquisition", () => {
  assert.match(source, /router\.push\(`\/market\/\$\{listing\.id\}`\)/);
  assert.doesNotMatch(source, /acquireListing/);
  assert.match(detail, /client\.getListing\(id\)/);
  assert.match(detail, /listing\.description/);
  assert.match(detail, /listing\.license_name/);
  assert.match(detail, /listing\.available_formats/);
  assert.match(detail, /listingThumbnails\(listing\)/);
});

test("acquisition remains an explicit action on the exact loaded listing", () => {
  assert.match(detail, /client\.acquireListing\(listing\.id, session\.workspaceId\)/);
  assert.match(detail, /onPress=\{\(\) => void acquire\(\)\}/);
  assert.match(detail, /client\.addFavorite\(listing\.id\)/);
  assert.match(detail, /client\.removeFavorite\(listing\.id\)/);
});

test("alternate reference 52/02 uses complete server-owned marketplace facets", () => {
  assert.match(source, /client\.marketplaceFacets\(\)/);
  assert.match(source, /verifiedFacets\(value\)/);
  assert.match(source, /value\.domains\.length !== MARKETPLACE_DOMAINS\.length/);
  assert.match(source, /Number\.isInteger\(facet\.count\)/);
  assert.match(source, /domain: selectedDomain \?\? undefined/);
  assert.match(source, /setSelectedDomain\(facet\.id\)/);
  assert.match(source, /Категории временно недоступны/);
});

test("marketplace search queries the canonical catalogue instead of the first local page", () => {
  assert.match(source, /setTimeout\(\(\) => setSearchTerm\(query\.trim\(\)\), 300\)/);
  assert.match(source, /q: searchTerm \|\| undefined/);
  assert.match(source, /const requestId = \+\+listingRequestId\.current/);
  assert.match(source, /requestId === listingRequestId\.current/);
  assert.doesNotMatch(source, /listings\.filter/);
});

test("marketplace browsing loads canonical result pages without duplicate listing ids", () => {
  assert.match(source, /const PAGE_SIZE = 24/);
  assert.match(source, /limit: PAGE_SIZE,[\s\S]*offset: 0/);
  assert.match(source, /const offset = nextOffset/);
  assert.match(source, /limit: PAGE_SIZE,[\s\S]*offset,/);
  assert.match(source, /new Set\(current\.map\(\(listing\) => listing\.id\)\)/);
  assert.match(source, /next\.filter\(\(listing\) => !seen\.has\(listing\.id\)\)/);
  assert.match(source, /setHasMore\(next\.length === PAGE_SIZE\)/);
  assert.match(source, /setNextOffset\(offset \+ next\.length\)/);
  assert.match(source, /Показать ещё/);
});

test("marketplace sort and free-only controls stay server-bound across every page", () => {
  assert.match(source, /type MarketSort = "popular" \| "newest" \| "cheapest"/);
  assert.match(source, /free: freeOnly \|\| undefined/);
  assert.match(source, /sort,/);
  assert.match(source, /setSort\(item\)/);
  assert.match(source, /setFreeOnly\(\(value\) => !value\)/);
  assert.match(source, /Только бесплатные/);
  assert.doesNotMatch(source, /listings\.sort/);
});

test("a missing or unreadable listing thumbnail keeps an honest placeholder", () => {
  assert.match(source, /\.catch\(\(\) => null\)/);
  assert.match(source, /ПРЕВЬЮ НЕДОСТУПНО/);
  assert.match(source, /Изображение товара не передано маркетплейсом/);
});
