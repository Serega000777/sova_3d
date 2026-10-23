import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/convert/page.tsx", import.meta.url), "utf8");

test("GLB self-conversion is presented as exact verification, not destructive conversion", () => {
  assert.match(page, /sourceExtension === "glb" && target === "glb"/);
  assert.match(page, /Verify GLB without changes/);
  assert.match(page, /byte-for-byte/);
  assert.match(page, /scene hierarchy, materials and animation channels/);
});
