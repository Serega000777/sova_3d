import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const engineer = readFileSync(new URL("../src/components/EngineerCard.tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/components/ModelViewer.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("numeric load results can highlight their measured model-space risk volume", () => {
  assert.match(engineer, /answer\.risk_region/);
  assert.match(engineer, /answer\.intent === "strength"/);
  assert.match(engineer, /answer\.verdict === "yes"[\s\S]*status-green/);
  assert.match(engineer, /Показать зону риска/);
  assert.match(project, /engineeringRiskRegion/);
  assert.match(engineer, /onShowRiskRegion\?\.\(null\)/);
  assert.match(project, /maximum-bending zone is highlighted in red/);
  assert.match(viewer, /riskRegions\.map/);
  assert.match(viewer, /color="#ff3b30"/);
});
