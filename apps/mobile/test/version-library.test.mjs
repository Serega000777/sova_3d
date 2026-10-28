import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  groupVersionAssets,
  uniqueVersionAssetCount,
  versionAssetRoleLabel,
} from "../src/version-library.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("O03 groups only real persisted version assets and canonical view angles", () => {
  const assets = [
    { asset_id: "model-1", role: "model" },
    { asset_id: "model-1", role: "preview" },
    { asset_id: "thumb-front", role: "thumbnail", thumbnail_angle: "front" },
    { asset_id: "thumb-iso", role: "thumbnail", thumbnail_angle: "iso" },
    { asset_id: "thumb-iso", role: "thumbnail", thumbnail_angle: "iso" },
  ];
  assert.deepEqual(groupVersionAssets(assets), [
    { role: "model", assetCount: 1, thumbnailAngles: [] },
    { role: "preview", assetCount: 1, thumbnailAngles: [] },
    { role: "thumbnail", assetCount: 2, thumbnailAngles: ["front", "iso"] },
  ]);
  assert.equal(uniqueVersionAssetCount(assets), 3);
  assert.equal(versionAssetRoleLabel("room_shell", true), "Оболочка комнаты");
});

test("O03 renders the selected immutable version inventory inside the editor", () => {
  assert.match(project, /accessibilityLabel=\{ru \? "Файлы выбранной версии"/);
  assert.match(project, /groupVersionAssets\(activeHistory\.assets\)/);
  assert.match(project, /uniqueVersionAssetCount\(activeHistory\.assets\)/);
  assert.match(project, /formatAssetBytes\(activeHistory\.total_asset_bytes\)/);
});
