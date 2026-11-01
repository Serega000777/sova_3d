import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { componentLibraryView } from "../src/component-library.ts";

const parts = [
  { id: "pi", name: "Raspberry Pi", kind: "board", screw: "M2.5", aliases: ["малина"] },
  { id: "motor", name: "N20 Motor", kind: "motor", screw: "M2", aliases: ["мотор"] },
];

test("component library combines search with honest catalogue groups", () => {
  assert.deepEqual(componentLibraryView(parts, "малина", "electronics").map((part) => part.id), ["pi"]);
  assert.deepEqual(componentLibraryView(parts, "motor", "mechanics").map((part) => part.id), ["motor"]);
  assert.deepEqual(componentLibraryView(parts, "motor", "electronics"), []);
  assert.deepEqual(
    componentLibraryView(parts, "", "favorites", new Set(["motor"])).map((part) => part.id),
    ["motor"],
  );
});

test("mobile component library uses the typed catalogue and terminal enclosure job", () => {
  const source = readFileSync(new URL("../app/components.tsx", import.meta.url), "utf8");
  assert.match(source, /client\.listComponents\(undefined, "ru"\)/);
  assert.match(source, /client\.listComponentFavorites/);
  assert.match(source, /client\.addComponentFavorite/);
  assert.match(source, /client\.removeComponentFavorite/);
  assert.match(source, /client\.createComponentModel/);
  assert.match(source, /client\.buildEnclosure/);
  assert.match(source, /await client\.waitForJob/);
  assert.match(source, /job\.status !== "succeeded"/);
  assert.match(source, /монтажный габарит/);
});

test("a built component or enclosure model can be inserted as a new node in another scene", () => {
  const source = readFileSync(new URL("../app/components.tsx", import.meta.url), "utf8");
  assert.match(source, /result\?\.model_asset_id/);
  assert.match(source, /\.listProjects\(session\.workspaceId\)/);
  assert.match(source, /project\.id !== createdModel\.projectId && project\.head_version_id/);
  assert.match(source, /client\.getScene\(target\.head_version_id\)/);
  assert.match(source, /client\.updateScene\(target\.head_version_id, body\)/);
  // existing scene nodes must round-trip without a forged appearance key
  assert.doesNotMatch(source, /node\.appearance/);
  assert.match(source, /asset_id: createdModel\.modelAssetId/);
  assert.match(source, /Вставить в выбранный проект/);
});
