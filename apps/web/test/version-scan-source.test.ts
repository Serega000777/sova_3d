import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { singleVersionScanAssetId } from "../src/lib/version-scan-source.ts";

const projectPage = readFileSync(
  new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
  "utf8",
);

test("one frozen scan source is unambiguous and duplicate links do not change it", () => {
  assert.equal(singleVersionScanAssetId([
    { asset_id: "model", role: "model" },
    { asset_id: "scan", role: "scan" },
    { asset_id: "scan", role: "scan" },
  ]), "scan");
  assert.equal(singleVersionScanAssetId([
    { asset_id: "scan-a", role: "scan" },
    { asset_id: "scan-b", role: "scan" },
  ]), null);
  assert.equal(singleVersionScanAssetId([{ asset_id: "model", role: "model" }]), null);
});

test("version history opens only the exact authorized scan download", () => {
  assert.match(projectPage, /singleVersionScanAssetId\(version\.assets\)/);
  assert.match(projectPage, /download\.asset_id !== assetId/);
  assert.match(projectPage, /openVersionScanSource\(scanAssetId\)/);
  assert.match(projectPage, /Открыть исходный скан версии/);
});
