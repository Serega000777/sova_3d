/** Item 26 follow-up: the house-box creator sends a typed L-turn stair and the plan editor draws
 *  every stair through the shared contract helper. Source-level checks: web tests have no DOM
 *  renderer, so they pin the wiring rather than simulate clicks. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseFloorPlan, stairPlanLines } from "@physical-ai/contracts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const wizard = read("../src/components/HouseBoxWizard.tsx");
const planPage = read("../src/app/plan/page.tsx");
const editor = read("../src/components/PlanEditor.tsx");

test("the house-box wizard submits discriminated straight, L-turn, U-turn or spiral stairs", () => {
  assert.match(wizard, /kind: "l_turn",\s+width_mm: stairWidthMm,[\s\S]+lower_step_count: lowerSteps,\s+upper_step_count: upperSteps,\s+turn: stairTurn,/);
  assert.match(wizard, /kind: "straight",\s+width_mm: stairWidthMm,[\s\S]+step_count: stepCount,/);
  assert.match(wizard, /kind: "u_turn",\s+width_mm: stairWidthMm,[\s\S]+flight_step_count: uFlightSteps,\s+turn: stairTurn,/);
  assert.match(wizard, /kind: "spiral",\s+diameter_mm: spiralDiameterMm,\s+post_diameter_mm: spiralPostDiameterMm,\s+step_count: spiralSteps,\s+sweep_deg: spiralSweepDeg,\s+turn: stairTurn,\s+placement: stairPlacement,\s+railing: false,/);
  // The landing is one riser and the comfort/fit checks gate submission like the server does.
  assert.match(wizard, /lowerSteps \+ upperSteps \+ 1/);
  assert.match(wizard, /2 \* uFlightSteps \+ 1/);
  assert.match(wizard, /strideMm < 550 \|\| strideMm > 700/);
  assert.match(wizard, /disabled=\{busy \|\| stairInvalid \|\| setbackInvalid\}/);
  assert.match(wizard, /upper_floor_setback_mm: effectiveUpperInset,/);
  assert.match(wizard, /const effectiveUpperInset = setbackEnabled && !perSideSetback \? upperFloorSetbackMm : 0;/);
  assert.match(wizard, /upper_floor_setback_sides_mm: effectiveSides\s+\? \{ x_min_mm: effectiveSides\.xMinMm, x_max_mm: effectiveSides\.xMaxMm, y_min_mm: effectiveSides\.yMinMm, y_max_mm: effectiveSides\.yMaxMm \}\s+: null,/);
  assert.match(wizard, /checkUpperFloorSetbackSides\(effectiveSides, lengthMm, widthMm\)/);
  assert.match(wizard, /stairFootprintFits\(\{ footprint: stairFootprint, placement: stairPlacement, houseLengthMm: lengthMm, houseWidthMm: widthMm, insets \}\)/);
  assert.match(wizard, /upperFloorSetbackSides: effectiveSides,[\s\S]+upperFloorSetbackSides: effectiveSides,/);
  assert.match(wizard, /lengthMm - 2 \* upperFloorSetbackMm < 2_000/);
});

test("the shared plan helper draws a U-turn through both parallel flights", () => {
  const plan = parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }],
    stairs: [{
      id: "stair_1_2_up",
      role: "up",
      from_floor: 0,
      to_floor: 1,
      kind: "u_turn",
      turn: "left",
      outline: [[4380, 3000], [7620, 3000], [7620, 5000], [4380, 5000]],
      flights: [
        { outline: [[4380, 3000], [6620, 3000], [6620, 4000], [4380, 4000]], step_count: 8, direction: "+x" },
        { outline: [[4380, 4000], [6620, 4000], [6620, 5000], [4380, 5000]], step_count: 8, direction: "-x" },
      ],
      landing: [[6620, 3000], [7620, 3000], [7620, 5000], [6620, 5000]],
      width_mm: 1000,
      run_mm: 4480,
      step_count: 17,
      tread_depth_mm: 280,
      riser_height_mm: 3000 / 17,
      railing: true,
    }],
  });
  const lines = stairPlanLines(plan!.stairs![0]!);
  assert.deepEqual(lines?.walkline, [[4380, 3500], [7120, 4000], [4380, 4500]]);
});

test("the wizard submits a strict winder stair without hidden fields", () => {
  const body = wizard.match(/\{\s+kind: "winder_turn",[\s\S]+?\n\s+\}/)?.[0] ?? "";
  assert.match(body, /lower_step_count: winderLowerSteps,\s+upper_step_count: winderUpperSteps,\s+newel_mm: newelMm,\s+turn: stairTurn,\s+placement: stairPlacement,\s+railing: false,/);
  // Nothing from the straight, L or U controls leaks, and the hidden railing state is not sent.
  assert.deepEqual(
    [...body.matchAll(/^\s+([a-z_]+):/gm)].map((match) => match[1]).sort(),
    ["kind", "lower_step_count", "material_id", "newel_mm", "placement", "railing", "tread_depth_mm", "turn", "upper_step_count", "width_mm"],
  );
  assert.doesNotMatch(body, /stepCount|uFlightSteps|[^r]lowerSteps|[^r]upperSteps|railing,/);
  // newel_mm belongs to the winder request only.
  assert.equal(wizard.match(/newel_mm/g)?.length, 1);
  assert.match(wizard, /\{!winderTurn && !spiralStair && \(\s+<label className="check">\s+<input type="checkbox" checked=\{railing\}/);
  assert.match(wizard, /winderTurn \? \(\s+<>[\s\S]+value=\{winderLowerSteps\} min=\{3\} max=\{24\}[\s\S]+value=\{newelMm\} min=\{200\} max=\{500\}/);
  assert.match(wizard, /ru: "Забежная, 90°", en: "Winder turn, 90°"/);
  assert.match(wizard, /checkWinderStair\(\{[\s\S]+upperFloorSetbackMm: effectiveUpperInset,/);
  assert.match(wizard, /winder\.problem && WINDER_STAIR_PROBLEM_TEXT\[winder\.problem\]\[language\]/);
  assert.match(wizard, /Railings, a newel post, structure and building codes are not modelled/);
});

test("the web spiral controls use the shared fail-closed check", () => {
  assert.match(wizard, /ru: "Винтовая", en: "Spiral"/);
  assert.match(wizard, /checkSpiralStair\(\{[\s\S]+diameterMm: spiralDiameterMm,[\s\S]+upperFloorSetbackMm: effectiveUpperInset,/);
  assert.match(wizard, /SPIRAL_STAIR_PROBLEM_TEXT\[spiral\.problem\]\[language\]/);
  assert.match(wizard, /value=\{spiralDiameterMm\} min=\{1_400\} max=\{3_200\}/);
  assert.match(wizard, /value=\{spiralPostDiameterMm\} min=\{100\} max=\{300\}/);
  assert.match(wizard, /value=\{spiralSteps\} min=\{10\} max=\{20\}/);
  assert.match(wizard, /value=\{spiralSweepDeg\} min=\{180\} max=\{330\}/);
  assert.match(wizard, /A helical railing, structure and building codes are not modelled/);
});

test("the plan editor draws treads and the walking line from stairPlanLines", () => {
  assert.match(editor, /const lines = stairPlanLines\(stair\);/);
  assert.match(editor, /lines\.treads\.map/);
  assert.match(editor, /stair\.newel && \(\s+<polygon/);
  assert.match(editor, /lines\.walkline\[Math\.floor\(lines\.walkline\.length \/ 2\)\]/);
  assert.match(editor, /stair\.kind === "winder_turn" \? " · W"/);
  assert.match(editor, /stair\.kind === "spiral" \? " · S"/);
  assert.match(planPage, /"winder_turn" \? \(ru \? " · с тремя забежными ступенями, без ограждения" : " · three winders, no railing"\)/);
  assert.match(planPage, /"spiral" \? \(ru \? " · винтовая вокруг центрального столба, без ограждения" : " · spiral around a central post, no railing"\)/);
  assert.match(editor, /<polyline points=\{lines\.walkline/);
  const plan = parseFloorPlan({
    rooms: [{ name: "Floor", outline: [[0, 0], [12000, 0], [12000, 8000], [0, 8000]] }],
    stairs: [{
      id: "stair_1_2_down",
      role: "down",
      from_floor: 0,
      to_floor: 1,
      kind: "l_turn",
      turn: "right",
      outline: [[4380, 4620], [6620, 4620], [6620, 2380], [7620, 2380], [7620, 5620], [4380, 5620]],
      flights: [
        { outline: [[4380, 4620], [6620, 4620], [6620, 5620], [4380, 5620]], step_count: 8, direction: "+x" },
        { outline: [[6620, 2380], [7620, 2380], [7620, 4620], [6620, 4620]], step_count: 8, direction: "-y" },
      ],
      landing: [[6620, 4620], [7620, 4620], [7620, 5620], [6620, 5620]],
      width_mm: 1000,
      run_mm: 4480,
      step_count: 17,
      tread_depth_mm: 280,
      riser_height_mm: 3000 / 17,
      railing: true,
    }],
  });
  const lines = stairPlanLines(plan!.stairs![0]!);
  // DOWN starts at the top of the right-turning upper flight and ends at the lower flight foot.
  assert.deepEqual(lines?.walkline, [[7120, 2380], [7120, 5120], [4380, 5120]]);
});
