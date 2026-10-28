import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const profile = readFileSync(new URL("../app/(tabs)/profile.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/EditModeSheet.tsx", import.meta.url), "utf8");

test("mobile experience mode persists and hides professional CAD tools from beginner mode", () => {
  assert.match(profile, /client\.updateMe\(\{ experience_mode: experienceMode \}\)/);
  assert.match(profile, /Режим не меняет тариф/);
  assert.match(project, /setExperienceMode\(me\.user\.experience_mode\)/);
  assert.match(project, /professional=\{experienceMode === "professional"\}/);
  assert.match(editor, /professional \? \(/);
  assert.match(editor, /Полный CAD-набор включается в профиле/);
});
