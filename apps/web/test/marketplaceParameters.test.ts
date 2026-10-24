import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/market/[id]/page.tsx", import.meta.url), "utf8");

test("a parametric listing rebuilds only changed exact CAD parameters", () => {
  assert.match(page, /listing\.parameters/);
  assert.match(page, /value\.value !== parameters\[index\]\.value/);
  assert.match(page, /acquireListing\(listing\.id, session\.workspaceId, changed\)/);
  assert.match(page, /orderFiles\(order\.id\)/);
  assert.match(page, /downloadDeliveredFile/);
  assert.match(page, /waitForJob\(acquired\.configuration_job_id/);
  assert.match(page, /Параметры взяты из неизменяемого CAD-дерева автора/);
});

test("a listing exposes only persisted canonical views and real creator context", () => {
  assert.match(page, /thumbnails\.map/);
  assert.match(page, /client\.download\(thumbnail\.asset_id\)/);
  assert.match(page, /role="radiogroup"/);
  assert.match(page, /thumbnailUrls\[thumbnailAngle\]/);
  assert.match(page, /page\.profile/);
  assert.match(page, /creator\.bio/);
  assert.match(page, /listing\.available_formats/);
  assert.doesNotMatch(page, /ensureVersionThumbnail/);
});

test("bundle contents use only persisted component previews and measured dimensions", () => {
  assert.match(page, /component\.thumbnail_asset_id/);
  assert.match(page, /client\.download\(component\.thumbnail_asset_id!\)/);
  assert.match(page, /component\.summary\?\.size_mm/);
  assert.match(page, /className="marketplace-component-thumbnail"/);
  assert.doesNotMatch(page, /ensureVersionThumbnail/);
});

test("facade bundles check addressed saved openings without claiming a pre-purchase mesh fit", () => {
  assert.match(page, /client\.facadeCompatibility\(listing\.id, targetProjectId\)/);
  assert.match(page, /facadeCompatibility\.openings\.map/);
  assert.match(page, /opening\.side/);
  assert.match(page, /opening\.floor/);
  assert.match(page, /opening\.matches\.map/);
  assert.match(page, /Точная mesh-проверка доступна после покупки/);
});

test("a product can be saved through the private favorites API", () => {
  assert.match(page, /client\.favoriteListings\(\)/);
  assert.match(page, /client\.addFavorite\(listing\.id\)/);
  assert.match(page, /client\.removeFavorite\(listing\.id\)/);
  assert.match(page, /aria-pressed=\{favorite\}/);
});
