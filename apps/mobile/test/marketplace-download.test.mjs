import assert from "node:assert/strict";
import test from "node:test";

import { verifiedMarketplaceDownloadUrl } from "../src/marketplace-download.ts";

const file = {
  asset_id: "asset-1",
  role: "model",
  labels: ["Основная модель"],
  format: "glb",
  mime: "model/gltf-binary",
  byte_size: 1_024,
};

const download = {
  asset_id: "asset-1",
  url: "https://assets.example/file.glb?signature=one",
  format: "glb",
  byte_size: 1_024,
  expires_in_seconds: 900,
  created_at: "2026-10-28T10:00:00Z",
};

test("reference 100 opens only the exact delivered marketplace file", () => {
  assert.equal(
    verifiedMarketplaceDownloadUrl(file, download),
    "https://assets.example/file.glb?signature=one",
  );
  for (const patch of [
    { asset_id: "asset-2" },
    { format: "stl" },
    { byte_size: 1_025 },
    { expires_in_seconds: 0 },
    { url: "file:///private/file.glb" },
    { url: "not a url" },
  ]) {
    assert.equal(verifiedMarketplaceDownloadUrl(file, { ...download, ...patch }), null);
  }
});
