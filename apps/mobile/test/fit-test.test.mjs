import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/FitTestSheet.tsx", import.meta.url), "utf8");

test("reference 53 is reachable from the real mobile project check tab", () => {
  assert.match(project, /Проверить посадку с другой деталью/);
  assert.match(project, /<FitTestSheet/);
  assert.match(project, /versionId=\{active\?\.id \?\? null\}/);
  assert.match(project, /await applyFix\(fix\)/);
});

test("mobile fit test reuses the exact two-version server path", () => {
  assert.match(sheet, /client\s*\.listProjects\(workspaceId\)/);
  assert.match(sheet, /client\.startFitTest\(\{/);
  assert.match(sheet, /version_a_id: versionId/);
  assert.match(sheet, /version_b_id: chosen\.head_version_id/);
  assert.match(sheet, /auto_place: true/);
  assert.match(sheet, /client\.waitForJob/);
  assert.match(sheet, /if \(job\.status !== "succeeded"\)/);
});

test("fit result keeps measured clearance distinct from an immutable fix", () => {
  assert.match(sheet, /measured\.max_penetration_mm/);
  assert.match(sheet, /measured\.min_clearance_mm/);
  assert.match(sheet, /advice\.recommendation/);
  assert.match(sheet, /onApplyFix\(advice\.fix!\)/);
  assert.match(sheet, /новую неизменяемую версию детали A/);
});
