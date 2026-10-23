import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/market/[id]/page.tsx", import.meta.url), "utf8");

test("a parametric listing rebuilds only changed exact CAD parameters", () => {
  assert.match(page, /listing\.parameters/);
  assert.match(page, /value\.value !== parameters\[index\]\.value/);
  assert.match(page, /acquireListing\(listing\.id, session\.workspaceId, changed\)/);
  assert.match(page, /waitForJob\(acquired\.configuration_job_id/);
  assert.match(page, /Параметры взяты из неизменяемого CAD-дерева автора/);
});
