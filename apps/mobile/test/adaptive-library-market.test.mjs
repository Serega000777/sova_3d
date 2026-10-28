import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const projects = readFileSync(new URL("../app/(tabs)/projects.tsx", import.meta.url), "utf8");
const market = readFileSync(new URL("../app/(tabs)/market.tsx", import.meta.url), "utf8");
const icons = readFileSync(new URL("../src/AppIcons.tsx", import.meta.url), "utf8");

test("project library uses compact phone rows and a visual tablet grid", () => {
  assert.match(projects, /width: "48%"/);
  assert.match(projects, /width: 112, height: 86/);
  assert.match(projects, /<GoalIcon id=\{goal\.id\}/);
  assert.match(projects, /<TemplateIcon id=\{template\.id\}/);
  assert.doesNotMatch(projects, /\{goal\.icon\}/);
});

test("market keeps advanced filters behind a counted adaptive control", () => {
  assert.match(market, /const \[filtersOpen, setFiltersOpen\]/);
  assert.match(market, /activeFilterCount/);
  assert.match(market, /accessibilityState=\{\{ expanded: filtersOpen \}\}/);
  assert.match(market, /filtersOpen \? <View/);
  assert.match(icons, /export function SlidersIcon/);
});
