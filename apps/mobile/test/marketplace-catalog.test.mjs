import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/(tabs)/market.tsx", import.meta.url), "utf8");

test("alternate reference 51/02 shows only canonical saved listing thumbnails", () => {
  assert.match(source, /listing\.thumbnail_asset_id/);
  assert.match(source, /client\.download\(listing\.thumbnail_asset_id\)/);
  assert.match(source, /thumbnailUrls\[listing\.id\]/);
  assert.match(source, /<Image/);
  assert.doesNotMatch(source, /versionThumbnailUrl|ensureVersionThumbnail|createThumbnail/);
});

test("a missing or unreadable listing thumbnail keeps an honest placeholder", () => {
  assert.match(source, /\.catch\(\(\) => null\)/);
  assert.match(source, /ПРЕВЬЮ НЕДОСТУПНО/);
  assert.match(source, /Изображение товара не передано маркетплейсом/);
});
