import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 71 web replacement mode requires guided views and a measured dimension", () => {
  assert.match(studio, /function toggleReplacementPartMode\(\)/);
  assert.match(studio, /setGuidedPhotos\(true\)/);
  assert.match(studio, /REPLACEMENT_DIMENSIONS\.map/);
  assert.match(studio, /parseReplacementMeasurements\(replacementMeasurements\)/);
  assert.match(studio, /replacementPartMode && measuredReplacement === null/);
  assert.match(studio, /Четыре ракурса и хотя бы один измеренный размер/);
});

test("reference 71 sends ordered assets only through the structured replacement payload", () => {
  const flow = studio.slice(
    studio.indexOf("async function sendCommand"),
    studio.indexOf("async function applyCommandProposal"),
  );
  assert.match(flow, /GUIDED_PHOTO_VIEWS\.map\(\(view\) => photos\.find/);
  assert.match(flow, /replacementViews = replacementPartMode/);
  assert.match(flow, /image_asset_ids: replacementPartMode \? \[\] : imageAssetIds/);
  assert.match(flow, /replacement_part: replacementPartMode/);
  assert.match(flow, /views: replacementViews!/);
  assert.match(flow, /measurements: measuredReplacement!/);
  assert.match(flow, /reference:\s*replacementPartMode\s*\? null/);
});

test("reference 71 copy does not present labelled views as hidden-geometry proof", () => {
  assert.match(studio, /не скрытую или утраченную геометрию/);
  assert.match(studio, /not hidden or missing geometry/);
  assert.doesNotMatch(studio, /автоматически восстановим утраченную геометрию/i);
});
