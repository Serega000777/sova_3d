import assert from "node:assert/strict";
import test from "node:test";

import { listingPrice, templateVisual } from "../src/projects-screen.ts";

test("known quick starts have distinct honest icons and category labels", () => {
  const templates = [
    ["organizer", "home"],
    ["phone-stand", "desk"],
    ["pipe-holder", "workshop"],
    ["mounting-plate", "workshop"],
    ["battery-tray", "home"],
    ["puck", "learn"],
  ];
  const visuals = templates.map(([id, category]) => templateVisual(id, category));

  assert.equal(new Set(visuals.map(({ glyph }) => glyph)).size, templates.length);
  assert.deepEqual(
    visuals.map(({ categoryLabel }) => categoryLabel),
    ["Для дома", "Рабочий стол", "Мастерская", "Мастерская", "Для дома", "Для старта"],
  );
});

test("unknown templates use a neutral icon and preserve the backend category", () => {
  assert.deepEqual(templateVisual("future-template", "medical"), {
    glyph: "◇",
    categoryLabel: "medical",
  });
});

test("marketplace price copy keeps free and paid values truthful", () => {
  assert.equal(listingPrice(0, "USD"), "Бесплатно");
  assert.equal(listingPrice(1299, "USD"), "12.99 USD");
});
