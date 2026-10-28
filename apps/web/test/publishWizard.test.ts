import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildListingBody,
  eligibleAnchorVersions,
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

test("anchor candidates require saved finalized files and exclude already published versions", () => {
  const versions = [
    { id: "published", state: "finalized", assets: [{}] },
    { id: "ready", state: "finalized", assets: [{}, {}] },
    { id: "empty", state: "finalized", assets: [] },
    { id: "draft", state: "draft", assets: [{}] },
  ];
  assert.deepEqual(
    eligibleAnchorVersions(versions, ["published"]).map((version) => version.id),
    ["ready"],
  );
});

test("tags preserve the existing comma-separated ListingBody semantics", () => {
  assert.deepEqual(listingTags(" printable, bracket, , wall "), ["printable", "bracket", "wall"]);
});

test("final wizard draft builds the domain-classified ListingBody", () => {
  assert.deepEqual(
    buildListingBody({
      anchorVersionId: "version-anchor",
      title: "  Wall bracket  ",
      description: "  Ready to print  ",
      category: "print",
      domain: "printable",
      subcategory: "wall-mounts",
      tags: "wall, bracket",
      priceText: "3,50",
      licence: "CC-BY-4.0",
      commercialUse: true,
      componentIds: ["version-a", "version-b"],
    }),
    {
      version_id: "version-anchor",
      title: "Wall bracket",
      description: "Ready to print",
      category: "print",
      domain: "printable",
      subcategory: "wall-mounts",
      tags: ["wall", "bracket"],
      price_cents: 350,
      currency: "USD",
      license_id: "CC-BY-4.0",
      component_version_ids: ["version-a", "version-b"],
    },
  );
  assert.equal(
    buildListingBody({
      anchorVersionId: "version-anchor",
      title: " ",
      description: "",
      category: "other",
      domain: "other",
      subcategory: "",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      commercialUse: true,
      componentIds: [],
    }),
    null,
  );
  assert.equal(
    buildListingBody({
      anchorVersionId: "",
      title: "Missing anchor",
      description: "",
      category: "other",
      domain: "other",
      subcategory: "",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      commercialUse: true,
      componentIds: [],
    }),
    null,
  );
  assert.equal(
    buildListingBody({
      anchorVersionId: "version-anchor",
      title: "Too many components",
      description: "",
      category: "other",
      domain: "other",
      subcategory: "",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      commercialUse: true,
      componentIds: Array.from({ length: PUBLISH_COMPONENT_LIMIT + 1 }, (_, index) => `v-${index}`),
    }),
    null,
  );
  assert.equal(
    buildListingBody({
      anchorVersionId: "version-anchor",
      title: "Bad taxonomy",
      description: "",
      category: "other",
      domain: "other",
      subcategory: "Not a slug",
      tags: "",
      priceText: "0",
      licence: "CC0-1.0",
      commercialUse: true,
      componentIds: [],
    }),
    null,
  );
});

test("M10 rejects a priced non-commercial draft but keeps a free one publishable", () => {
  const draft = {
    anchorVersionId: "version-anchor",
    title: "Shared model",
    description: "",
    category: "other" as const,
    domain: "other" as const,
    subcategory: "",
    tags: "",
    priceText: "1.00",
    licence: "CC-BY-NC-4.0",
    commercialUse: false,
    componentIds: [],
  };
  assert.equal(buildListingBody(draft), null);
  assert.equal(buildListingBody({ ...draft, priceText: "0" })?.price_cents, 0);
});

test("the real PublishCard wires all four steps to one final publish action", () => {
  for (const step of ["Файлы", "Описание", "Цена и права", "Проверка"]) {
    assert.ok(publishCard.includes(step), step);
  }
  assert.match(publishCard, /if \(step !== STEP_IDS\.length - 1\) \{\s*next\(\);\s*return;/);
  assert.match(publishCard, /const body = buildListingBody\(/);
  assert.match(publishCard, /anchorVersionId: effectiveAnchorVersionId/);
  assert.match(publishCard, /eligibleAnchorVersions/);
  assert.match(publishCard, /setComponentIds\(\(all\) => all\.filter\(\(id\) => id !== nextId\)\)/);
  assert.equal(publishCard.match(/await onPublish\(body\)/g)?.length, 1);
  assert.match(publishCard, /disabled=\{\s*!componentIds\.includes\(version\.id\)[\s\S]*?componentIds\.length >= PUBLISH_COMPONENT_LIMIT/);
  assert.match(publishCard, /marketplaceFacets\.domains\.find/);
  assert.match(publishCard, /item\.label_ru/);
  assert.doesNotMatch(publishCard, /Subcategory slug/);
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
  assert.match(publishCard, /id="publish-license-conflict"/);
  assert.match(publishCard, /selectedLicence\.commercial_use/);
  assert.match(publishCard, /selectedLicence\.attribution_required/);
  assert.match(publishCard, /selectedLicence\.derivatives/);
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
  assert.match(market, /min_price_cents: price\?\.min/);
  assert.match(market, /max_price_cents: price\?\.max/);
  assert.match(market, /bundle_only: bundleOnly \|\| undefined/);
  assert.match(market, /format: formatId \|\| undefined/);
  assert.match(market, /editable: capabilities\.editable \|\| undefined/);
  assert.match(market, /has_2d_plan: capabilities\.hasPlan \|\| undefined/);
  assert.match(market, /print_ready: capabilities\.printReady \|\| undefined/);
  assert.match(market, /\["stl", "3mf", "step", "brep", "glb", "gltf", "obj", "ply"\]/);
  assert.match(market, /useState<"relevant" \| "newest" \| "popular" \| "cheapest">\("relevant"\)/);
  assert.match(market, /const listingRequestId = useRef\(0\)/);
  assert.match(market, /const requestId = \+\+listingRequestId\.current/);
  assert.match(market, /requestId === listingRequestId\.current\) setListings\(nextListings\)/);
  assert.match(market, /<option value="relevant">\{t\.sort\.relevant\}<\/option>/);
  assert.match(market, /Укажите корректный диапазон цены/);
  assert.match(market, /Укажите три положительных размера/);
  assert.match(market, /className="marketplace-lane"/);
  assert.match(
    market,
    /key=\{`project-fit-\$\{listing\.id\}`\}[\s\S]*?variant="lane"[\s\S]*?onAddToCart=\{addToCart\}/,
  );
  assert.match(
    market,
    /key=\{`\$\{id\}-\$\{listing\.id\}`\}[\s\S]*?variant="lane"[\s\S]*?onAddToCart=\{addToCart\}/,
  );
  assert.doesNotMatch(market, /recommendedLane/);
});

test("the marketplace shell exposes desktop categories and a mobile filter surface", () => {
  const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
  assert.match(market, /className="marketplace-category-rail"/);
  assert.match(market, /className="marketplace-mobile-nav"/);
  assert.match(market, /aria-expanded=\{filtersOpen\}/);
  assert.match(market, /const featured = showcase\.popular\[0\] \?\? showcase\.newest\[0\]/);
  assert.match(market, /variant="featured"/);
  assert.match(css, /\.marketplace-catalog-layout\s*\{/);
  assert.match(css, /\.marketplace-filters\.mobile-open/);
  assert.match(css, /grid-template-columns: repeat\(5, minmax\(0, 1fr\)\)/);
});

test("the marketplace category tree uses server facets and separate domain filters", () => {
  const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
  assert.match(market, /client\.marketplaceFacets\(\)/);
  assert.match(market, /next\.domains\.length === DOMAINS\.length/);
  assert.match(market, /setFacetsAvailable\(false\)/);
  assert.match(market, /facetsAvailable \? facet\.count : "—"/);
  assert.match(market, /Счётчики разделов недоступны/);
  assert.match(market, /client\.favoriteListings\(\)/);
  assert.match(market, /\["all", "favorites", "feed", "mine"\]/);
  assert.match(market, /domain: domain \?\? undefined/);
  assert.match(market, /subcategory: subcategory \?\? undefined/);
  assert.match(market, /facet\.subcategories\.map/);
  assert.match(market, /child\.label_ru/);
  assert.match(market, /facet\.count/);
  assert.match(market, /Назначение \/ формат/);
  assert.match(market, /проверено для печати/);
});
