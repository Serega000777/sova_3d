import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/AssemblyInspectionSheet.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("reference 67 reads the canonical server assembly manifest", () => {
  assert.match(client, /inspectAssembly\(versionId: string\)/);
  assert.match(client, /assembly-inspection/);
  assert.match(sheet, /client\.inspectAssembly\(versionId\)/);
  assert.match(sheet, /inspection\.bom\.map/);
  assert.match(project, /Сборка деталей/);
});

test("the exploded preview uses the exact server order and reversible world transforms", () => {
  assert.match(sheet, /inspection\.exploded_order/);
  assert.match(project, /const rank = new Map\(explodedPreview\.order/);
  assert.match(project, /worldTransform\[2\]!\[3\] \+=/);
  assert.match(project, /displayedSceneParts/);
  assert.match(sheet, /Собрать preview/);
});

test("the assembly UI keeps unsupported verification boundaries explicit", () => {
  assert.match(sheet, /Связи mate\/joint и столкновения всей сцены не проверяются/);
  assert.match(sheet, /не выдаётся за инструкцию монтажа/);
  assert.match(client, /no inferred joints or collision claims/);
});
