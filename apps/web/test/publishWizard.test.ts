import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildListingBody,
  eligibleComponentVersions,
  listingTags,
  parsePriceCents,
  PUBLISH_COMPONENT_LIMIT,
  PUBLISH_PRICE_LIMIT_CENTS,
} from "../src/lib/publishWizard.ts";

const publishCard = readFileSync(
  new URL("../src/components/PublishCard.tsx", import.meta.url),
  "utf8",
);

test("price validation accepts non-negative RU/EN decimals and rejects invalid values", () => {
  assert.equal(parsePriceCents("0"), 0);
  assert.equal(parsePriceCents("12.34"), 1234);
  assert.equal(parsePriceCents("12,34"), 1234);
  assert.equal(parsePriceCents("1.999"), null);
  assert.equal(parsePriceCents("0.001"), null);
  assert.equal(parsePriceCents("-0.01"), null);
  assert.equal(parsePriceCents(""), null);
  assert.equal(parsePriceCents("free"), null);
  assert.equal(parsePriceCents("0x10"), null);
  assert.equal(parsePriceCents("100000"), PUBLISH_PRICE_LIMIT_CENTS);
  assert.equal(parsePriceCents("100000.01"), null);
});

test("bundle candidates require a finalized non-anchor version with saved assets", () => {
  const versions = [
    { id: "anchor", state: "finalized", assets: [{}] },
    { id: "ready", state: "finalized", assets: [{}] },
    { id: "empty", state: "finalized", assets: [] },
    { id: "draft", state: "draft", assets: [{}] },
  ];
  assert.deepEqual(
    eligibleComponentVersions(versions, "anchor").map((version) => version.id),
    ["ready"],
  );
});

test("tags preserve the existing comma-separated ListingBody semantics", () => {
  assert.deepEqual(listingTags(" printable, bracket, , wall "), ["printable", "bracket", "wall"]);
});

test("final wizard draft builds the existing ListingBody without API extensions", () => {
  assert.deepEqual(
    buildListingBody({
      title: "  Wall bracket  ",
      description: "  Ready to print  ",
      category: "print",
      tags: "wall, bracket",
      priceText: "3,50",
      licence: "CC-BY-4.0",
      componentIds: ["version-a", "version-b"],
    }),
    {
      version_id: null,
      title: "Wall bracket",
      description: "Ready to print",
      category: "print",
      tags: ["wall", "bracket"],
      price_cents: 350,
      currency: "USD",
      license_id: "CC-BY-4.0",
      component_version_ids: ["version-a", "version-b"],
    },
  );
  assert.equal(
    buildListingBody({
      title: " ",
      description: "",
      category: "other",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      componentIds: [],
    }),
    null,
  );
  assert.equal(
    buildListingBody({
      title: "Too many components",
      description: "",
      category: "other",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      componentIds: Array.from({ length: PUBLISH_COMPONENT_LIMIT + 1 }, (_, index) => `v-${index}`),
    }),
    null,
  );
});

test("the real PublishCard wires all four steps to one final publish action", () => {
  for (const step of ["Файлы", "Описание", "Цена и права", "Проверка"]) {
    assert.ok(publishCard.includes(step), step);
  }
  assert.match(publishCard, /if \(step !== STEP_IDS\.length - 1\) \{\s*next\(\);\s*return;/);
  assert.match(publishCard, /const body = buildListingBody\(/);
  assert.equal(publishCard.match(/await onPublish\(body\)/g)?.length, 1);
  assert.match(publishCard, /disabled=\{\s*!componentIds\.includes\(version\.id\)[\s\S]*?componentIds\.length >= PUBLISH_COMPONENT_LIMIT/);
});

test("the wizard resets per project and after a successful publish", () => {
  assert.match(
    publishCard,
    /useEffect\(\(\) => \{[\s\S]*?setComponentIds\(\[\]\);[\s\S]*?\}, \[project\.id\]\);/,
  );
  assert.match(publishCard, /await onPublish\(body\);\s*resetWizard\(\);/);
});

test("step changes are announced and move focus to the active heading", () => {
  assert.match(publishCard, /stepHeadingRef\.current\?\.focus\(\)/);
  assert.equal(publishCard.match(/ref=\{stepHeadingRef\} tabIndex=\{-1\}/g)?.length, 4);
  assert.match(publishCard, /aria-live="polite"/);
  assert.match(
    publishCard,
    /aria-describedby=\{parsedPrice === null[\s\S]*?publish-price-help publish-price-error/,
  );
  assert.match(publishCard, /id="publish-price-help"/);
  assert.match(publishCard, /id="publish-price-error"/);
});

test("marketplace cards resolve the canonical listing thumbnail without generating one", () => {
  const card = readFileSync(new URL("../src/components/ListingCard.tsx", import.meta.url), "utf8");
  assert.match(card, /listing\.thumbnail_asset_id/);
  assert.match(card, /client\.download\(listing\.thumbnail_asset_id\)/);
  assert.doesNotMatch(card, /ensureVersionThumbnail/);
  assert.match(card, /className="marketplace-card-image"/);
});

test("the marketplace showcase uses real newest and popular API sorts", () => {
  const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
  assert.match(market, /searchListings\(\{ sort: "newest", limit: 6 \}\)/);
  assert.match(market, /searchListings\(\{ sort: "popular", limit: 6 \}\)/);
  assert.match(market, /max_width_mm: fit\?\.width/);
  assert.match(market, /max_depth_mm: fit\?\.depth/);
  assert.match(market, /max_height_mm: fit\?\.height/);
  assert.match(market, /rotate_to_fit: fit\?\.rotate/);
  assert.match(market, /Укажите три положительных размера/);
  assert.match(market, /className="marketplace-lane"/);
  assert.doesNotMatch(market, /recommendedLane/);
});
