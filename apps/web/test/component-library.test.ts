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
  assert.match(page, /job\.status !== "succeeded"\s*\|\| job\.project_id !== accepted\.project_id/);
  assert.match(page, /setCreatedModel\(\{ projectId: accepted\.project_id/);
  assert.match(library, /href="\/components"/);
});

test("catalogue copy keeps mounting geometry distinct from a visual product twin", () => {
  const page = readFileSync(new URL("../src/app/components/page.tsx", import.meta.url), "utf8");
  assert.match(page, /без выдуманного внешнего вида/);
  assert.match(page, /косметические поверхности не моделируются/);
});

test("reference 65 web inserts the exact built asset as a new root scene object", () => {
  const page = readFileSync(new URL("../src/app/components/page.tsx", import.meta.url), "utf8");
  assert.match(page, /typeof result\?\.model_asset_id !== "string"/);
  assert.match(page, /client\.listProjects\(session\.workspaceId\)/);
  assert.match(page, /project\.id !== createdModel\.projectId && Boolean\(project\.head_version_id\)/);
  assert.match(page, /const freshTarget = await client\.getProject\(target\.id\)/);
  assert.match(page, /freshTarget\.id !== target\.id \|\| !freshTarget\.head_version_id/);
  assert.match(page, /const scene = await client\.getScene\(targetVersionId\)/);
  assert.match(page, /scene\.version_id !== targetVersionId/);
  assert.match(page, /asset_id: createdModel\.modelAssetId/);
  assert.match(page, /parent_id: null/);
  assert.match(page, /transform: SCENE_IDENTITY_TRANSFORM/);
  assert.match(page, /const updated = await client\.updateScene\(targetVersionId, body\)/);
  assert.match(page, /updated\.parent_version_id !== targetVersionId/);
  assert.match(page, /node\.asset_id === createdModel\.modelAssetId/);
});
