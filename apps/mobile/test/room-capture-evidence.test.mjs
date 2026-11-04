import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const resultScreen = readFileSync(new URL("../app/scan/[id].tsx", import.meta.url), "utf8");
const native = readFileSync(
  new URL("../modules/expo-room-plan/ios/ExpoRoomPlanView.swift", import.meta.url),
  "utf8",
);
const types = readFileSync(
  new URL("../modules/expo-room-plan/src/ExpoRoomPlan.types.ts", import.meta.url),
  "utf8",
);
const client = readFileSync(
  new URL("../../../packages/contracts/src/client.ts", import.meta.url),
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

test("reference 78 keeps one ARKit frame and uploads Apple's merged structure", () => {
  assert.match(native, /arSession\.run\(ARWorldTrackingConfiguration\(\)\)/);
  assert.match(native, /RoomCaptureView\([\s\S]*arSession: RoomPlanStructureRegistry\.session/);
  assert.match(native, /stop\(pauseARSession: false\)/);
  assert.match(native, /StructureBuilder\(\)\.capturedStructure\(from: rooms\)/);
  assert.match(native, /"coordinate_space": "shared_arkit_world"/);
  assert.match(native, /payload\["floor_elevation_m"\]/);
  assert.match(types, /structureSessionId: string/);
  assert.match(types, /structure\?: RoomPlanStructureEvent/);
  assert.match(screen, /setScanRoomPlanStructure\(scan\.id, roomPlanStructure\)/);
  assert.match(screen, /capture_source: "apple_roomplan_structure"/);
  assert.match(client, /\/room-plan-structure/);
});

test("multi-floor RoomPlan review exposes measured levels and a height-preserving shell claim", () => {
  assert.match(resultScreen, /floor_count\?: number/);
  assert.match(
    resultScreen,
    /const floorCount = captureStats\?\.room_plan\?\.floor_count \?\? 1/,
  );
  assert.match(resultScreen, /label: "Этажи"/);
  assert.match(resultScreen, /Здесь показан нижний этаж/);
  assert.match(resultScreen, /Exact shell сохраняет их на измеренных/);
  assert.match(resultScreen, /высотах и показывается только после успешной обработки/);
});

test("a missing or subset native merge falls back to honest separate rooms", () => {
  assert.match(screen, /const completeStructure =/);
  assert.match(screen, /if \(completeStructure && latestStructure\)/);
  assert.match(screen, /for \(const entry of chosen\)/);
  assert.match(screen, /native merge недоступен/);
});
