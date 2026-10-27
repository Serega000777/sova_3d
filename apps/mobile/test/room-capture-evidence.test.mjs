import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const native = readFileSync(
  new URL("../modules/expo-room-plan/ios/ExpoRoomPlanView.swift", import.meta.url),
  "utf8",
);
const types = readFileSync(
  new URL("../modules/expo-room-plan/src/ExpoRoomPlan.types.ts", import.meta.url),
  "utf8",
);

test("reference 78 reports RoomPlan doors and windows instead of dropping them", () => {
  assert.match(native, /room\.doors\.count \+ room\.windows\.count \+ room\.openings\.count/);
  assert.match(native, /"doors": room\.doors\.count/);
  assert.match(native, /"windows": room\.windows\.count/);
  assert.match(types, /doors\?: number/);
  assert.match(types, /windows\?: number/);
  assert.match(screen, /`двери \$\{progress\.doors\}`/);
  assert.match(screen, /`окна \$\{progress\.windows\}`/);
});

test("older development builds retain an honest aggregate opening count", () => {
  assert.match(screen, /progress\.doors === undefined \|\| progress\.windows === undefined/);
  assert.match(screen, /`стены \$\{progress\.walls\} · проёмы \$\{progress\.openings\}/);
  assert.doesNotMatch(screen, /82%/);
});
