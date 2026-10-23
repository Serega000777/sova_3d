import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/market/[id]/page.tsx", import.meta.url), "utf8");

test("a parametric listing rebuilds only changed exact CAD parameters", () => {
  assert.match(page, /listing\.parameters/);
  assert.match(page, /value\.value !== parameters\[index\]\.value/);
  assert.match(page, /acquireListing\(listing\.id, session\.workspaceId, changed\)/);
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
