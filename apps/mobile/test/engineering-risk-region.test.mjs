import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { engineeringRiskBox } from "../src/engineering-risk-region.ts";

test("server box becomes one exact model-space risk overlay", () => {
  assert.deepEqual(engineeringRiskBox({
    region: { kind: "box", min_mm: [-10, 2, 3], max_mm: [4, 9, 12] },
    target: "body",
  }), {
    key: "engineering-load-risk",
    min: [-10, 2, 3],
    max: [4, 9, 12],
  });
});

test("non-box, non-finite and reversed regions fail closed", () => {
  assert.equal(engineeringRiskBox(null), null);
  assert.equal(engineeringRiskBox({
    region: { kind: "lasso", axis: "z", depth_mm: 1, points_mm: [[0, 0], [1, 0], [1, 1]] },
  }), null);
  assert.equal(engineeringRiskBox({
    region: { kind: "box", min_mm: [0, 0, 0], max_mm: [0, 1, 1] },
  }), null);
  assert.equal(engineeringRiskBox({
    region: { kind: "box", min_mm: [0, 0, 0], max_mm: [1, Number.NaN, 1] },
  }), null);
});

test("mobile engineer action feeds the raw server region to the 3D viewer", () => {
  const card = readFileSync(new URL("../src/EngineerCard.tsx", import.meta.url), "utf8");
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
  assert.match(card, /Показать зону риска/);
  assert.match(card, /onShowRiskRegion\(answer\.risk_region\)/);
  assert.match(project, /riskRegions=\{engineeringRiskBoxOverlay \? \[engineeringRiskBoxOverlay\] : \[\]\}/);
  assert.match(project, /Это предварительная оценка, не FEA/);
  assert.match(viewer, /new THREE\.BoxGeometry\(\.\.\.dimensions\)/);
  assert.match(viewer, /wireframe: true/);
});
