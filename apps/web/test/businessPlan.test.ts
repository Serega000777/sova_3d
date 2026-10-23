import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/business/page.tsx", import.meta.url), "utf8");

test("business starter uses measured analyses and refuses demand claims", () => {
  assert.match(page, /client\.createBusinessPlan/);
  assert.match(page, /version_ids: selected/);
  assert.match(page, /Себестоимость/);
  assert.match(page, /спрос не заявляется/);
  assert.match(page, /Нужен ISO-рендер перед публикацией/);
  assert.match(page, /product\.analysis_status/);
  assert.match(page, /product\.printability_score/);
  assert.match(page, /product\.production_instructions\.map/);
  assert.match(page, /instruction\[ru \? "ru" : "en"\]/);
  assert.match(page, /client\.versionThumbnailUrl\(versionId\)/);
  assert.match(page, /product\.render_asset_id/);
  assert.match(page, /renderUrls\[product\.version_id\]/);
  assert.match(page, /Создать ISO-рендер/);
});
