import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { formatGenerationEstimate } from "../src/generation-estimate.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

const estimate = {
  provider: "shap_e",
  model: "text300M",
  provider_version: null,
  credits: "4.00",
  cost_usd: null,
  latency_seconds_min: 60,
  latency_seconds_max: 4200,
  target_format: "glb",
  assumptions: ["self-hosted"],
};

test("mobile formats an honest bounded self-hosted estimate", () => {
  assert.equal(
    formatGenerationEstimate(estimate, true),
    "Оценка до запуска: 1–70 мин, 4.00 кредитов (self-hosted — точная цена в USD недоступна).",
  );
  assert.equal(
    formatGenerationEstimate({ ...estimate, latency_seconds_max: 61, cost_usd: "0.125" }, false),
    "Pre-launch estimate: ~1 min, 4.00 credits ($0.125).",
  );
});

test("malformed or inconsistent estimate evidence fails closed", () => {
  for (const patch of [
    { provider: "" },
    { model: "" },
    { target_format: "stl" },
    { latency_seconds_min: Number.NaN },
    { latency_seconds_min: -1 },
    { latency_seconds_min: 500, latency_seconds_max: 100 },
    { credits: "" },
    { cost_usd: "free" },
    { cost_usd: "-1" },
  ]) {
    assert.equal(formatGenerationEstimate({ ...estimate, ...patch }, true), null);
  }
});

test("mobile organic generation requests and invalidates the exact typed estimate", () => {
  assert.match(project, /client\.estimateThreeDGeneration\(id, \{/);
  assert.match(project, /mode: "text"/);
  assert.match(project, /purpose: "standard"/);
  assert.match(project, /target_format: "glb"/);
  assert.match(project, /pbr: false/);
  assert.match(project, /rig: "none"/);
  assert.match(project, /organicEstimateRevision\.current \+= 1/);
  assert.match(project, /onChangeText=\{\(value\) => \{ setOrganicPrompt\(value\); invalidateOrganicEstimate\(\); \}\}/);
  assert.match(project, /Оценить время и цену/);
  assert.match(project, /formatGenerationEstimate\(organicEstimate, ru\)/);
});
