import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { componentLibraryView } from "../src/lib/component-library.ts";

const components = [
  { id: "board", name: "Raspberry Pi", kind: "board", screw: "M2.5", aliases: ["rpi"] },
  { id: "motor", name: "NEMA 17", kind: "motor", screw: "M3", aliases: ["stepper"] },
] as never;

test("component view combines honest grouping, favorites, and word search", () => {
  assert.deepEqual(componentLibraryView(components, "rpi m2", "electronics", new Set()).map((item) => item.id), ["board"]);
  assert.deepEqual(componentLibraryView(components, "", "mechanics", new Set()).map((item) => item.id), ["motor"]);
  assert.deepEqual(componentLibraryView(components, "", "favorites", new Set(["motor"])).map((item) => item.id), ["motor"]);
});

test("reference 65 web catalogue uses private favorites and a terminal exact build", () => {
  const page = readFileSync(new URL("../src/app/components/page.tsx", import.meta.url), "utf8");
  const library = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /client\.listComponents\(undefined, language\)/);
  assert.match(page, /client\.listComponentFavorites\(\)/);
  assert.match(page, /client\.addComponentFavorite\(componentId\)/);
  assert.match(page, /client\.removeComponentFavorite\(componentId\)/);
  assert.match(page, /client\.createComponentModel\(sourceId/);
  assert.match(page, /accepted\.component_id !== sourceId/);
  assert.match(page, /accepted\.model_scope !== "mounting_geometry"/);
  assert.match(page, /job\.status !== "succeeded" \|\| job\.project_id !== accepted\.project_id/);
  assert.match(page, /router\.push\(`\/projects\/\$\{accepted\.project_id\}`\)/);
  assert.match(library, /href="\/components"/);
});

test("catalogue copy keeps mounting geometry distinct from a visual product twin", () => {
  const page = readFileSync(new URL("../src/app/components/page.tsx", import.meta.url), "utf8");
  assert.match(page, /без выдуманного внешнего вида/);
  assert.match(page, /косметические поверхности не моделируются/);
});
