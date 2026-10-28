import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const settings = readFileSync(new URL("../src/app/settings/page.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("experience mode persists from settings and selects the default Studio surface", () => {
  assert.match(settings, /experience_mode: experienceMode/);
  assert.match(settings, /value="beginner"/);
  assert.match(settings, /value="professional"/);
  assert.match(settings, /Это меняет интерфейс, а не подписку/);
  assert.match(studio, /result\.user\.experience_mode === "professional"/);
  assert.match(studio, /setComplexity\(professional \? "advanced" : "simple"\)/);
  assert.match(studio, /setShowAllTools\(professional\)/);
});
