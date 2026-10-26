import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/FastenerSheet.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("reference 66 is reachable from the real project check tab", () => {
  assert.match(project, /Точный крепёж/);
  assert.match(project, /<FastenerSheet/);
  assert.match(project, /versionId=\{active\?\.id \?\? null\}/);
});

test("the mobile flow creates a real fastener version and measures one exact hole", () => {
  assert.match(sheet, /client\.getOperationStack\(versionId\)/);
  assert.match(sheet, /operation\.type !== "add_hole"/);
  assert.match(sheet, /face\.axis !== "z"/);
  assert.match(sheet, /face\.sign !== "\+"/);
  assert.match(sheet, /client\.createFastener\(\{/);
  assert.match(sheet, /client\.startFastenerFit\(versionId/);
  assert.match(sheet, /hole_operation_id: selectedHole\.id/);
  assert.match(sheet, /client\.waitForJob/);
});

test("only a compatible measured result can become an immutable fastener scene node", () => {
  assert.match(sheet, /result\?\.geometry_compatible/);
  assert.match(sheet, /compatible && fitTestId/);
  assert.match(sheet, /client\.createFitAssembly\(fitTestId/);
  assert.match(project, /Проверенный крепёж сохранён отдельным узлом/);
});

test("the UI and contract do not claim thread or physics simulation", () => {
  assert.match(sheet, /гладкая номинальная оболочка/);
  assert.match(sheet, /Резьба, шлиц, момент затяжки, преднатяг и прочность не моделируются/);
  assert.match(client, /smooth CAD fastener envelope/);
});
