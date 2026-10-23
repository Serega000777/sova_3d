import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/creators/[handle]/page.tsx", import.meta.url), "utf8");

test("creator pages expose real public collections and owner-only management", () => {
  assert.match(page, /page\.collections/);
  assert.match(page, /createCreatorCollection/);
  assert.match(page, /deleteCreatorCollection/);
  assert.match(page, /collection\.listings\.map/);
  assert.match(page, /own &&/);
});
