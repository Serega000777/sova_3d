import assert from "node:assert/strict";
import test from "node:test";

import { getProjectGoal, PROJECT_GOALS } from "../src/project-goals.ts";

test("T-231 exposes the ten agreed project starts once", () => {
  assert.equal(PROJECT_GOALS.length, 10);
  assert.equal(new Set(PROJECT_GOALS.map((goal) => goal.id)).size, 10);
});

test("every scan goal routes to a real capture subject", () => {
  const scans = PROJECT_GOALS.filter((goal) => goal.source === "scan");
  assert.deepEqual(
    scans.map((goal) => goal.scanSubject),
    ["object", "room", "home", "exterior"],
  );
});

test("creation defaults select the intended output pipelines", () => {
  assert.equal(getProjectGoal("printable_object")?.target, "print");
  assert.equal(getProjectGoal("game_character")?.target, "game");
  assert.equal(getProjectGoal("game_character")?.workflow, "organic");
  assert.equal(getProjectGoal("dimensioned_part")?.target, "cad");
  assert.equal(getProjectGoal("missing"), null);
});
