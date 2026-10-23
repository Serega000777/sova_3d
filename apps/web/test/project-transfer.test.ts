import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 40 offers selected view-only files without weakening owner handoff", () => {
  assert.match(page, /client\.createProjectSharePackage/);
  assert.match(page, /expires_minutes: 15/);
  assert.match(page, /asset_ids: shareSelected/);
  assert.match(page, /format !== "glb"/);
  assert.match(page, /format !== "pdf"/);
  assert.match(page, /format !== "png"/);
  assert.match(page, /Ссылки только для просмотра/);
  assert.match(page, /navigator\.clipboard\.writeText/);
  assert.match(page, /client\.transferProject/);
  assert.match(page, /transferConfirmation !== project\?\.name/);
});
