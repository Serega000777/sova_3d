import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const creator = readFileSync(new URL("../src/HouseBoxCreator.tsx", import.meta.url), "utf8");
const projects = readFileSync(new URL("../app/(tabs)/projects.tsx", import.meta.url), "utf8");
const textCreator = readFileSync(new URL("../src/HouseTextCreator.tsx", import.meta.url), "utf8");

test("mobile house creation exposes the exact typed house-box job", () => {
  assert.match(projects, /houseMode.*"params".*"text".*"blank"/);
  assert.match(projects, /<HouseBoxCreator/);
  assert.match(creator, /client\.buildHouseBox\(/);
  assert.match(creator, /client\.waitForJob\(accepted\.job\.job_id/);
  assert.match(creator, /onCreated\(accepted\.project_id\)/);
});

test("mobile sends discriminated straight, L-turn, U-turn or spiral stair parameters", () => {
  assert.match(creator, /kind: "straight"[\s\S]+step_count: dimensions\.straightSteps/);
  assert.match(creator, /kind: "l_turn"[\s\S]+lower_step_count: dimensions\.lowerSteps/);
  assert.match(creator, /upper_step_count: dimensions\.upperSteps/);
  assert.match(creator, /kind: "u_turn"[\s\S]+flight_step_count: dimensions\.uFlightSteps/);
  assert.match(creator, /kind: "spiral"[\s\S]+diameter_mm: dimensions\.spiralDiameter,[\s\S]+post_diameter_mm: dimensions\.spiralPostDiameter,[\s\S]+step_count: dimensions\.spiralSteps,[\s\S]+sweep_deg: dimensions\.spiralSweep,[\s\S]+railing: false/);
  assert.match(creator, /turn,[\s\S]+placement: "center"/);
  assert.match(creator, /2 \* rise \+ dimensions\.tread < 550/);
  assert.match(creator, /stairFootprintFits\(\{\s+footprint: \{ x: footprintLength, y: footprintWidth \},\s+placement: "center",[\s\S]+insets: upperFloorInsets\(upperInset, setbackSides\),/);
  assert.match(creator, /stairKind === "straight"[\s\S]+\[dimensions\.straightSteps\][\s\S]+\[dimensions\.lowerSteps, dimensions\.upperSteps\][\s\S]+\[dimensions\.spiralDiameter, dimensions\.spiralPostDiameter, dimensions\.spiralSteps, dimensions\.spiralSweep\][\s\S]+\[dimensions\.uFlightSteps\]/);
  assert.match(creator, /Лестницы пока доступны только для прямоугольного дома/);
  assert.match(creator, /upper_floor_setback_mm: upperInset,/);
  assert.match(creator, /Отступ верхних этажей, мм/);
});

test("mobile spiral controls mirror the bounded server rules", () => {
  assert.match(creator, /value="spiral" selected=\{stairKind\} label="Винтовая"/);
  assert.match(creator, /checkSpiralStair\(\{[\s\S]+diameterMm: dimensions\.spiralDiameter,[\s\S]+upperFloorSetbackMm: upperInset,\s+upperFloorSetbackSides: setbackSides,/);
  assert.match(creator, /SPIRAL_STAIR_PROBLEM_TEXT\[spiral\.problem\]\.ru/);
  assert.match(creator, /value=\{spiralDiameterMm\}[\s\S]+value=\{spiralPostDiameterMm\}[\s\S]+value=\{spiralSteps\}[\s\S]+value=\{spiralSweepDeg\}/);
  assert.match(creator, /Винтовое ограждение, прочность и строительные нормы не моделируются/);
});

test("mobile winder stair sends only its own bounded fields and no railing", () => {
  const body = creator.match(/\{\s+kind: "winder_turn",[\s\S]+?\n\s+\}/)?.[0] ?? "";
  assert.match(body, /lower_step_count: dimensions\.winderLowerSteps,\s+upper_step_count: dimensions\.winderUpperSteps,\s+newel_mm: dimensions\.newel,\s+turn,\s+placement: "center",\s+railing: false,/);
  assert.doesNotMatch(body, /straightSteps|uFlightSteps|dimensions\.lowerSteps|dimensions\.upperSteps|railing: true/);
  assert.equal(creator.match(/newel_mm/g)?.length, 1);
  assert.match(creator, /value="winder_turn" selected=\{stairKind\} label="Забежная 90°"/);
  assert.match(creator, /stairKind === "winder_turn" \? \([\s\S]+value=\{winderLowerSteps\}[\s\S]+value=\{winderUpperSteps\}[\s\S]+value=\{newelMm\}/);
  assert.match(creator, /\[dimensions\.winderLowerSteps, dimensions\.winderUpperSteps, dimensions\.newel\]/);
  assert.match(creator, /checkWinderStair\(\{[\s\S]+upperFloorSetbackMm: upperInset,\s+upperFloorSetbackSides: setbackSides,/);
  assert.match(creator, /WINDER_STAIR_PROBLEM_TEXT\[winder\.problem\]\.ru/);
  assert.match(creator, /Ограждение, столб, прочность и нормы для этого поворота не моделируются/);
});

test("mobile per-side setback replaces the symmetric one and mirrors the server bounds", () => {
  assert.match(creator, /const upperInset = setbackAllowed && !perSideSetback \? dimensions\.upperFloorSetback : 0;/);
  assert.match(creator, /xMinMm: dimensions\.setbackXMin, xMaxMm: dimensions\.setbackXMax, yMinMm: dimensions\.setbackYMin, yMaxMm: dimensions\.setbackYMax/);
  assert.match(creator, /checkUpperFloorSetbackSides\(setbackSides, dimensions\.length, dimensions\.width\)/);
  assert.match(creator, /\|\| sidesProblem !== null/);
  assert.match(creator, /upper_floor_setback_sides_mm: setbackSides\s+\? \{ x_min_mm: setbackSides\.xMinMm, x_max_mm: setbackSides\.xMaxMm, y_min_mm: setbackSides\.yMinMm, y_max_mm: setbackSides\.yMaxMm \}\s+: null,/);
  assert.match(creator, /Отступ по сторонам \(терраса, балкон\)/);
  assert.match(creator, /Это геометрия, а не расчёт консолей или опор/);
});

test("description mode states the current multi-floor shell boundary", () => {
  assert.match(textCreator, /2–3 этажа получает отдельные shell каждого уровня и плоскую крышу/);
  assert.doesNotMatch(textCreator, /без лестниц, крыши, окон и комнат/);
});
