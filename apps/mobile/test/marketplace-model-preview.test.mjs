import assert from "node:assert/strict";
import test from "node:test";

import { verifiedMarketplaceModelPreview } from "../src/marketplace-model-preview.ts";

const download = {
  asset_id: "asset-1",
  url: "https://objects.example.test/model.stl?signature=ok",
  format: "stl",
  byte_size: 2048,
  expires_in_seconds: 900,
  created_at: "2026-10-28T12:00:00Z",
};

test("accepts only the exact non-empty STL or GLB listing asset", () => {
  assert.deepEqual(verifiedMarketplaceModelPreview("asset-1", download), {
    url: download.url,
    format: "stl",
  });
  assert.equal(
    verifiedMarketplaceModelPreview("asset-1", { ...download, format: "GLB", url: "http://localhost/model.glb" })?.format,
    "glb",
  );
});

test("rejects substituted, empty, expired, unsupported, or unsafe model downloads", () => {
  for (const patch of [
    { asset_id: "asset-2" },
    { byte_size: 0 },
    { expires_in_seconds: 0 },
    { format: "obj" },
    { url: "file:///tmp/model.stl" },
    { url: "not a URL" },
  ]) {
    assert.equal(verifiedMarketplaceModelPreview("asset-1", { ...download, ...patch }), null);
  }
});
