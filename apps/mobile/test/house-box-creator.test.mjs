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

test("mobile sends discriminated straight or L-turn stair parameters", () => {
  assert.match(creator, /kind: "straight"[\s\S]+step_count: dimensions\.straightSteps/);
  assert.match(creator, /kind: "l_turn"[\s\S]+lower_step_count: dimensions\.lowerSteps/);
  assert.match(creator, /upper_step_count: dimensions\.upperSteps/);
  assert.match(creator, /turn,[\s\S]+placement: "center"/);
  assert.match(creator, /2 \* rise \+ dimensions\.tread < 550/);
  assert.match(creator, /Лестницы пока доступны только для прямоугольного дома/);
});

test("description mode states the current multi-floor shell boundary", () => {
  assert.match(textCreator, /2–3 этажа получает отдельные shell каждого уровня и плоскую крышу/);
  assert.doesNotMatch(textCreator, /без лестниц, крыши, окон и комнат/);
});
