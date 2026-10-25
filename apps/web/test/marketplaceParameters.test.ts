import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/market/[id]/page.tsx", import.meta.url), "utf8");
const floorPlans = readFileSync(new URL("../src/components/MarketplaceFloorPlans.tsx", import.meta.url), "utf8");
const facadeSchedule = readFileSync(new URL("../src/components/MarketplaceFacadeSchedule.tsx", import.meta.url), "utf8");
const planEditor = readFileSync(new URL("../src/components/PlanEditor.tsx", import.meta.url), "utf8");

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

test("house listings show only typed server-derived area, floors, dimensions and rooms", () => {
  assert.match(page, /listing\.house\.gross_floor_area_m2/);
  assert.match(page, /listing\.house\.floors/);
  assert.match(page, /listing\.house\.length_mm/);
  assert.match(page, /listing\.house\.width_mm/);
  assert.match(page, /listing\.house\.shape/);
  assert.match(page, /listing\.house\.rooms\.map/);
  assert.match(page, /room\.floor_index \+ 1/);
  assert.match(page, /room\.area_m2\.toFixed/);
  assert.match(page, /подтверждены неизменяемой операцией автопланировки/);
});

test("house products render only structured immutable floor plans without document claims", () => {
  assert.match(page, /listing\.floor_plans/);
  assert.match(page, /MarketplaceFloorPlans/);
  assert.match(floorPlans, /role="tablist"/);
  assert.match(floorPlans, /selected\.plan\.walls\.length/);
  assert.match(floorPlans, /selected\.plan\.rooms\.length/);
  assert.match(floorPlans, /не PDF\/DWG-файл/);
  assert.match(planEditor, /export function PlanPreview/);
});

test("exact facade products show a job-proven opening schedule without claiming a DWG", () => {
  assert.match(page, /listing\.facade/);
  assert.match(page, /MarketplaceFacadeSchedule/);
  assert.match(facadeSchedule, /facade\.openings\.map/);
  assert.match(facadeSchedule, /opening\.side/);
  assert.match(facadeSchedule, /opening\.floor/);
  assert.match(facadeSchedule, /это не чертёж DWG/);
});

test("bundle contents use only persisted component previews and measured dimensions", () => {
  assert.match(page, /component\.thumbnail_asset_id/);
  assert.match(page, /client\.download\(component\.thumbnail_asset_id!\)/);
  assert.match(page, /component\.summary\?\.size_mm/);
  assert.match(page, /className="marketplace-bundle-tile"/);
  assert.doesNotMatch(page, /ensureVersionThumbnail/);
});

test("bundle overview and file list share stable numbers without invented previews", () => {
  assert.match(page, /const bundleMembers = \[/);
  assert.match(page, /bundleMembers\.map\(\(member, index\)/);
  assert.match(page, /marketplace-bundle-board/);
  assert.match(page, /marketplace-module-number/);
  assert.match(page, /Нет сохранённого превью/);
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
