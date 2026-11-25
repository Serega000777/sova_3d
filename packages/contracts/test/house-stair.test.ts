/** The shared winder-turn check mirrors the server's bounded rules for web and mobile. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  checkWinderStair,
  WINDER_STAIR_LIMITS,
  WINDER_STAIR_PROBLEM_TEXT,
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
