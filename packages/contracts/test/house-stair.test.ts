/** The shared winder-turn check mirrors the server's bounded rules for web and mobile. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  checkSpiralStair,
  checkUpperFloorSetbackLevels,
  checkUpperFloorSetbackSides,
  checkWinderStair,
  stackedUpperFloorInsets,
  upperFloorSetbackProblemText,
  SPIRAL_STAIR_LIMITS,
  SPIRAL_STAIR_PROBLEM_TEXT,
  stairFootprintFits,
  UPPER_FLOOR_SETBACK_PROBLEM_TEXT,
  upperFloorInsets,
  WINDER_STAIR_LIMITS,
  WINDER_STAIR_PROBLEM_TEXT,
  type SpiralStairInput,
  type WinderStairInput,
} from "../src/house-stair.ts";

const base: WinderStairInput = {
  widthMm: 1_000,
  treadMm: 280,
  lowerSteps: 7,
  upperSteps: 7,
  newelMm: 250,
  placement: "center",
  houseLengthMm: 12_000,
  houseWidthMm: 8_000,
  floorHeightMm: 3_000,
  upperFloorSetbackMm: 0,
};

test("the default winder stair is accepted with derived metrics", () => {
  const check = checkWinderStair(base);
  assert.equal(check.problem, null);
  assert.equal(check.riserCount, 17);
  assert.ok(Math.abs(check.riseMm - 3_000 / 17) < 1e-9);
  assert.ok(Math.abs(check.winderGoingMm - 550 * Math.PI / 6) < 1e-9);
  assert.deepEqual(check.footprint, { x: 3_210, y: 3_210 });
});

test("every server bound is rejected by the client with its own message", () => {
  const cases: [Partial<WinderStairInput>, string][] = [
    [{ widthMm: 699 }, "width"],
    [{ widthMm: 2_001 }, "width"],
    [{ widthMm: Number.NaN }, "width"],
    [{ treadMm: 401 }, "tread"],
    [{ lowerSteps: 2 }, "flight_steps"],
    [{ upperSteps: 25 }, "flight_steps"],
    [{ lowerSteps: 7.5 }, "flight_steps"],
    [{ upperSteps: Number.NaN }, "flight_steps"],
    [{ newelMm: 199 }, "newel"],
    [{ newelMm: 501 }, "newel"],
    [{ newelMm: Number.POSITIVE_INFINITY }, "newel"],
    [{ lowerSteps: 3, upperSteps: 3 }, "risers"],
    [{ lowerSteps: 14, upperSteps: 14 }, "risers"],
    [{ floorHeightMm: 6_000 }, "rise"],
    [{ floorHeightMm: Number.NaN }, "rise"],
    [{ treadMm: 400 }, "stride"],
    [{ newelMm: 500 }, "winder_stride"],
    [{ houseLengthMm: 3_909 }, "fit"],
    [{ houseWidthMm: Number.NaN }, "fit"],
    [{ upperFloorSetbackMm: 2_100 }, "fit"],
    [{ upperFloorSetbackMm: 100, placement: "left" }, "setback_placement"],
  ];
  for (const [change, problem] of cases) {
    assert.equal(checkWinderStair({ ...base, ...change }).problem, problem, JSON.stringify(change));
  }
  assert.equal(checkWinderStair({ ...base, houseLengthMm: 3_910, houseWidthMm: 3_910 }).problem, null);
  assert.deepEqual(WINDER_STAIR_LIMITS.flightSteps, [3, 24]);
  for (const text of Object.values(WINDER_STAIR_PROBLEM_TEXT)) assert.ok(text.ru && text.en);
});

const spiralBase: SpiralStairInput = {
  diameterMm: 2_200,
  postDiameterMm: 200,
  stepCount: 15,
  sweepDeg: 300,
  placement: "center",
  houseLengthMm: 12_000,
  houseWidthMm: 8_000,
  floorHeightMm: 3_000,
  upperFloorSetbackMm: 0,
};

test("the default spiral stair is accepted with server-identical derived metrics", () => {
  const check = checkSpiralStair(spiralBase);
  assert.equal(check.problem, null);
  assert.equal(check.riseMm, 200);
  assert.equal(check.treadAngleDeg, 20);
  assert.equal(check.clearWidthMm, 1_000);
  assert.equal(check.walklineRadiusMm, 600);
  assert.ok(Math.abs(check.goingMm - 600 * Math.PI / 9) < 1e-9);
  assert.deepEqual(check.footprint, { x: 2_200, y: 2_200 });
});

test("the shared spiral check rejects every server boundary before submit", () => {
  const cases: [Partial<SpiralStairInput>, string][] = [
    [{ diameterMm: 1_399 }, "diameter"],
    [{ diameterMm: Number.NaN }, "diameter"],
    [{ postDiameterMm: 99 }, "post"],
    [{ postDiameterMm: Number.POSITIVE_INFINITY }, "post"],
    [{ stepCount: 9 }, "steps"],
    [{ stepCount: 15.5 }, "steps"],
    [{ sweepDeg: 179 }, "sweep"],
    [{ floorHeightMm: 6_000 }, "rise"],
    [{ stepCount: 21 }, "steps"],
    [{ floorHeightMm: 2_200, stepCount: 10, sweepDeg: 330 }, "tread_angle"],
    [{ diameterMm: 1_500 }, "clear_width"],
    [{ sweepDeg: 180 }, "going"],
    [{ floorHeightMm: 2_400, stepCount: 20, sweepDeg: 330, diameterMm: 3_000, postDiameterMm: 300 }, "stride"],
    [{ houseLengthMm: 2_899 }, "fit"],
    [{ houseWidthMm: 2_899 }, "fit"],
    [{ upperFloorSetbackMm: 100, placement: "left" }, "fit"],
  ];
  for (const [change, problem] of cases) {
    assert.equal(checkSpiralStair({ ...spiralBase, ...change }).problem, problem, JSON.stringify(change));
  }
  assert.equal(checkSpiralStair({ ...spiralBase, houseLengthMm: 2_900, houseWidthMm: 2_900 }).problem, null);
  assert.deepEqual(SPIRAL_STAIR_LIMITS.steps, [10, 20]);
  for (const text of Object.values(SPIRAL_STAIR_PROBLEM_TEXT)) assert.ok(text.ru && text.en);
});

test("per-side upper-floor setbacks mirror the server bounds", () => {
  const none = { xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 };
  assert.equal(checkUpperFloorSetbackSides({ ...none, xMaxMm: 3_000, yMinMm: 1_000 }, 12_000, 8_000), null);
  assert.equal(checkUpperFloorSetbackSides(none, 12_000, 8_000), "empty");
  assert.equal(checkUpperFloorSetbackSides({ ...none, xMinMm: -1 }, 12_000, 8_000), "side");
  assert.equal(checkUpperFloorSetbackSides({ ...none, xMinMm: 10_001 }, 12_000, 8_000), "side");
  assert.equal(checkUpperFloorSetbackSides({ ...none, xMinMm: Number.NaN }, 12_000, 8_000), "side");
  assert.equal(checkUpperFloorSetbackSides({ ...none, yMinMm: 6_001 }, 12_000, 8_000), "upper_floor");
  assert.equal(checkUpperFloorSetbackSides({ ...none, xMinMm: 5_000, xMaxMm: 5_000 }, 12_000, 8_000), null);
  for (const text of Object.values(UPPER_FLOOR_SETBACK_PROBLEM_TEXT)) assert.ok(text.ru && text.en);
  assert.deepEqual(upperFloorInsets(500), { xMinMm: 500, xMaxMm: 500, yMinMm: 500, yMaxMm: 500 });
  assert.deepEqual(upperFloorInsets(500, { ...none, yMaxMm: 10 }), { ...none, yMaxMm: 10 });
});

test("stair fit follows the server placement against the inset upper walls", () => {
  const none = { xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 };
  const straight = { footprint: { x: 4_760, y: 1_000 }, houseLengthMm: 12_000, houseWidthMm: 8_000 };
  assert.equal(stairFootprintFits({ ...straight, placement: "left", insets: none }), true);
  // A left-wall stair is cut by a left setback but not by one on the opposite wall.
  assert.equal(stairFootprintFits({ ...straight, placement: "left", insets: { ...none, yMinMm: 1 } }), false);
  assert.equal(stairFootprintFits({ ...straight, placement: "left", insets: { ...none, yMaxMm: 1_000 } }), true);
  // A centred stair is cut once an X inset reaches its centred run.
  assert.equal(stairFootprintFits({ ...straight, placement: "center", insets: { ...none, xMaxMm: 3_270 } }), true);
  assert.equal(stairFootprintFits({ ...straight, placement: "center", insets: { ...none, xMaxMm: 3_271 } }), false);

  const winder = { ...base, placement: "left" as const };
  assert.equal(checkWinderStair({ ...winder, upperFloorSetbackSides: { ...none, yMaxMm: 1_000 } }).problem, null);
  assert.equal(checkWinderStair({ ...winder, upperFloorSetbackSides: { ...none, yMinMm: 100 } }).problem, "setback_placement");
  // Explicit sides replace the symmetric value instead of adding to it.
  assert.equal(checkWinderStair({ ...winder, upperFloorSetbackMm: 100, upperFloorSetbackSides: { ...none, yMaxMm: 100 } }).problem, null);
  assert.equal(checkSpiralStair({ ...spiralBase, placement: "left", upperFloorSetbackSides: { ...none, yMaxMm: 1_000 } }).problem, null);
  assert.equal(checkSpiralStair({ ...spiralBase, placement: "left", upperFloorSetbackSides: { ...none, yMinMm: 1 } }).problem, "fit");
});

test("per-floor setbacks mirror the server's stepped-level rules", () => {
  const none = { xMinMm: 0, xMaxMm: 0, yMinMm: 0, yMaxMm: 0 };
  const floor2 = { ...none, xMaxMm: 1_500 };
  const floor3 = { ...none, xMaxMm: 3_000, yMinMm: 1_000 };
  assert.equal(checkUpperFloorSetbackLevels([floor2, floor3], 3, 12_000, 8_000), null);
  assert.equal(checkUpperFloorSetbackLevels([floor2], 3, 12_000, 8_000), "levels");
  assert.equal(checkUpperFloorSetbackLevels([floor2, floor3], 2, 12_000, 8_000), "levels");
  assert.equal(checkUpperFloorSetbackLevels([none, none], 3, 12_000, 8_000), "empty");
  // A floor without its own setback is allowed while another level has one.
  assert.equal(checkUpperFloorSetbackLevels([none, floor3], 3, 12_000, 8_000), null);
  assert.equal(checkUpperFloorSetbackLevels([none, { ...none, xMinMm: Number.NaN }], 3, 12_000, 8_000), "side");
  assert.equal(checkUpperFloorSetbackLevels([none, { ...none, yMinMm: 6_001 }], 3, 12_000, 8_000), "upper_floor");
  assert.equal(checkUpperFloorSetbackLevels([floor3, floor2], 3, 12_000, 8_000), "overhang");
  for (const problem of ["levels", "overhang", "side", "empty", "upper_floor"] as const) {
    const text = upperFloorSetbackProblemText(problem);
    assert.ok(text.ru && text.en);
  }

  // One stair has to fit the tightest wall of every level.
  const insets = stackedUpperFloorInsets([{ ...none, yMaxMm: 500 }, { ...none, yMinMm: 500, yMaxMm: 500 }]);
  assert.deepEqual(insets, { ...none, yMinMm: 500, yMaxMm: 500 });
  const straight = { footprint: { x: 4_760, y: 1_000 }, houseLengthMm: 12_000, houseWidthMm: 8_000 };
  assert.equal(stairFootprintFits({ ...straight, placement: "left", insets }), false);
  assert.equal(stairFootprintFits({ ...straight, placement: "center", insets }), true);
  const winder = { ...base, placement: "left" as const };
  assert.equal(checkWinderStair({ ...winder, upperFloorSetbackSides: insets }).problem, "setback_placement");
});
