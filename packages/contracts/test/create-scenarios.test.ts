/** The Create menu: the same scenarios, guidance and processing choices on every client. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CREATE_SCENARIOS,
  EXPORT_FORMATS,
  QUALITY_PRESETS,
  SCENARIO_GROUPS,
  defaultProcessing,
  estimateResultMb,
  frameMessage,
  frameProgress,
  getScenario,
  normalizeProcessing,
  scenarioPath,
  scenariosIn,
  suggestMethod,
} from "../src/create-scenarios.ts";
import { getProjectGoal } from "../src/project-goals.ts";

test("every scenario sits in a known group and every group has scenarios", () => {
  for (const scenario of CREATE_SCENARIOS) {
    assert.ok(SCENARIO_GROUPS.some((g) => g.id === scenario.group), scenario.id);
  }
  for (const group of SCENARIO_GROUPS) assert.ok(scenariosIn(group.id).length > 0, group.id);
  assert.equal(new Set(CREATE_SCENARIOS.map((s) => s.id)).size, CREATE_SCENARIOS.length);
});

test("a scenario either starts from a real project goal or opens a real page", () => {
  for (const scenario of CREATE_SCENARIOS) {
    assert.ok(scenario.goal || scenario.route, `${scenario.id} leads nowhere`);
    if (scenario.goal) assert.ok(getProjectGoal(scenario.goal), `${scenario.id}: unknown goal ${scenario.goal}`);
    if (scenario.route) assert.ok(scenario.route.startsWith("/"));
  }
});

test("every scan scenario has guidance in both languages and the real scans cover the object", () => {
  for (const scenario of scenariosIn("scan")) {
    assert.ok(scenario.guide.length >= 3, scenario.id);
    for (const step of scenario.guide) {
      assert.ok(step.title.ru && step.title.en);
      assert.ok(step.tips.length > 0);
      for (const tip of step.tips) assert.ok(tip.ru && tip.en);
    }
  }
  assert.deepEqual(getScenario("object_scan")?.limits, { minFrames: 20, maxFrames: 150 });
  assert.equal(getScenario("nope"), null);
});

test("scenario paths go to the scanner, a page or the create form", () => {
  const room = getScenario("room_scan")!;
  assert.equal(scenarioPath(room, "room"), "/scanner?source=phone&subject=room");
  assert.equal(scenarioPath(getScenario("floor_plan")!), "/plan");
  assert.equal(scenarioPath(getScenario("game_character")!), "/new?scenario=game_character");
});

test("frame progress tracks the minimum and the maximum", () => {
  const limits = { minFrames: 20, maxFrames: 150 };
  assert.equal(frameProgress(0, limits).state, "empty");
  const few = frameProgress(8, limits);
  assert.equal(few.state, "too_few");
  assert.equal(few.remainingToMinimum, 12);
  assert.equal(few.canProcess, false);
  assert.equal(frameProgress(20, limits).canProcess, true);
  assert.equal(frameProgress(80, limits).state, "ready");
  assert.equal(frameProgress(150, limits).state, "full");
  assert.equal(frameProgress(999, limits).fraction, 1);
  assert.ok(Math.abs(few.minimumMark - 20 / 150) < 1e-9);
  assert.match(frameMessage(few, limits, "ru"), /Ещё 12/);
  assert.match(frameMessage(few, limits, "en"), /12 more/);
  assert.equal(frameProgress(-5, limits).count, 0);
});

test("the default processing keeps training and public listing OFF until the person opts in", () => {
  const defaults = defaultProcessing();
  assert.equal(defaults.allowTraining, false);
  assert.equal(defaults.publicVisibility, false);
  assert.equal(defaults.quality, "default");
});

test("stored processing options are repaired, never trusted", () => {
  assert.deepEqual(normalizeProcessing(null), defaultProcessing());
  const fixed = normalizeProcessing({ quality: "ultra", texture: 3000, format: "exe", maskObject: "yes", allowTraining: 1 });
  assert.deepEqual(fixed, defaultProcessing());
  const kept = normalizeProcessing({ method: "gaussian_splat", quality: "dense", texture: 4096, format: "usdz", maskObject: true, allowTraining: true });
  assert.equal(kept.method, "gaussian_splat");
  assert.equal(kept.quality, "dense");
  assert.equal(kept.texture, 4096);
  assert.equal(kept.format, "usdz");
  assert.equal(kept.maskObject && kept.allowTraining, true);
});

test("every quality level and format explains what it is for", () => {
  for (const q of QUALITY_PRESETS) assert.ok(q.use.ru && q.use.en);
  for (const f of EXPORT_FORMATS) assert.ok(f.best.ru && f.best.en);
  assert.deepEqual(QUALITY_PRESETS.map((q) => q.id), ["fast", "default", "dense", "raw"]);
});

test("the method suggestion follows what the person needs", () => {
  assert.equal(suggestMethod({ printing: true, shiny: true }), "photogrammetry");
  assert.equal(suggestMethod({ shiny: true }), "gaussian_splat");
  assert.equal(suggestMethod({ fineDetail: true }), "gaussian_splat");
  assert.equal(suggestMethod({}), "photogrammetry");
});

test("a heavier setting never estimates a smaller result", () => {
  const sizes = QUALITY_PRESETS.map((q) => estimateResultMb(60, q.id, 2048));
  assert.deepEqual([...sizes].sort((a, b) => a - b), sizes);
  assert.ok(estimateResultMb(60, "default", 4096) > estimateResultMb(60, "default", 1024));
  assert.ok(estimateResultMb(120, "default", 2048) > estimateResultMb(30, "default", 2048));
});
