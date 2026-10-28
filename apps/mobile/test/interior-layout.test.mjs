import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/FurniturePlacementSheet.tsx", import.meta.url), "utf8");
const annotator = readFileSync(new URL("../src/PlanAnnotator.tsx", import.meta.url), "utf8");

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

test("reference 79 supports direct metric drag-to-place on the linked 2D plan", () => {
  assert.match(sheet, /Перетащить на 2D-плане/);
  assert.match(project, /setFurniturePlanDragging\(true\)/);
  assert.match(project, /setViewMode\("2d"\)/);
  assert.match(project, /setFurniturePoint\(\[point\[0\], point\[1\], furniturePoint\[2\]\]\)/);
  assert.match(annotator, /kind: "furniture"/);
  assert.match(annotator, /onFurniturePlacementChange\?\.\(at\)/);
  assert.match(annotator, /width=\{furniturePlacement\.widthMm\}/);
  assert.match(annotator, /depthMm/);
});

test("validated floor-plan placement cannot float above its floor", () => {
  assert.match(project, /z_mm: activeFloorPlan \? 0 : furniturePoint\[2\]/);
  assert.match(sheet, /editable=\{!floorPlanId \|\| axis !== 2\}/);
  assert.match(sheet, /Z зафиксирован на 0 мм/);
  assert.match(sheet, /onPointChange\(\[point\[0\], point\[1\], 0\]\)/);
});
