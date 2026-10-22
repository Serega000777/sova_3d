import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/FurniturePlacementSheet.tsx", import.meta.url), "utf8");

test("reference 79 binds mobile furniture placement to the exact active floor plan", () => {
  assert.match(project, /floor_plan_id: activeFloorPlan\.id/);
  assert.match(project, /clearance_mm: furnitureClearance/);
  assert.match(project, /floorPlanId=\{activeFloorPlan\?\.id \?\? null\}/);
  assert.match(project, /useState\(150\)/);
});

test("the sheet exposes honest validated and unrestricted placement states", () => {
  assert.match(sheet, /Проверка по текущему 2D-плану/);
  assert.match(sheet, /Без проверки по плану/);
  assert.match(sheet, /\[0, 150, 300\]/);
  assert.match(sheet, /Сервер не добавит предмет вне комнаты/);
});
