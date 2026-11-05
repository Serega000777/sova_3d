import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  analysisMatchesManufacturingContext,
  calculateManufacturingEstimate,
  manufacturingEstimateInput,
  restoredManufacturingEstimate,
} from "../src/lib/manufacturing-estimate.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../src/components/ManufacturingEstimateCard.tsx", import.meta.url), "utf8");

const analysis = {
  id: "analysis-91",
  kind: "analysis",
  project_version_id: "version-91",
  printer_profile_id: "printer-91",
  material_id: "pla",
  report: {
    metrics: {
      mass_g: 100,
      support_mass_g: 20,
      layers: 120,
      print_time_min: 120,
      material_cost: 10,
      support_cost: 2,
      total_cost: 12,
      currency: "RUB",
    },
  },
} as never;

const saved = {
  id: "estimate-91",
  analysis_id: "analysis-91",
  project_version_id: "version-91",
  created_by: "user-1",
  printer_profile_id: "printer-91",
  material_id: "pla",
  currency: "RUB",
  material_cost: "12.0000",
  print_time_min: "120.0000",
  machine_rate_per_hour: "10.0000",
  printer_power_w: "100.0000",
  electricity_rate_per_kwh: "0.5000",
  postprocess_hours: "2.0000",
  postprocess_rate_per_hour: "3.0000",
  machine_cost: "20.00",
  electricity_cost: "0.10",
  postprocess_cost: "6.00",
  total_cost: "38.10",
  created_at: "2026-11-05T09:00:00Z",
} as never;

test("reference 91 computes the explicit rate pairs and restores the server snapshot", () => {
  const draft = {
    machineRatePerHour: "10",
    printerPowerW: "100",
    electricityRatePerKwh: "0.5",
    postprocessHours: "2",
    postprocessRatePerHour: "3",
  };
  assert.deepEqual(manufacturingEstimateInput(draft), {
    machine_rate_per_hour: 10,
    printer_power_w: 100,
    electricity_rate_per_kwh: 0.5,
    postprocess_hours: 2,
    postprocess_rate_per_hour: 3,
  });
  assert.deepEqual(calculateManufacturingEstimate(12, 120, draft), {
    valid: true,
    machineCost: 20,
    electricityCost: 0.1,
    postprocessCost: 6,
    totalCost: 38.1,
  });
  assert.equal(
    restoredManufacturingEstimate(saved, analysis, "version-91", "printer-91", "pla")?.totalCost,
    38.1,
  );
  assert.match(studio, /client\.createManufacturingEstimate\(sourceAnalysis\.id, input\)/);
  assert.match(card, /savedEstimate\.total_cost/);
});

test("manufacturing snapshots fail closed and clear/reload across version profile and material changes", () => {
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "printer-91", "pla"), true);
  assert.equal(analysisMatchesManufacturingContext(analysis, "other-version", "printer-91", "pla"), false);
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "other-printer", "pla"), false);
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "printer-91", "petg"), false);
  assert.equal(restoredManufacturingEstimate(saved, analysis, "other-version", "printer-91", "pla"), null);
  assert.equal(restoredManufacturingEstimate(saved, analysis, "version-91", "other-printer", "pla"), null);
  assert.equal(restoredManufacturingEstimate(saved, analysis, "version-91", "printer-91", "petg"), null);
  assert.equal(restoredManufacturingEstimate({ ...saved, total_cost: "999.00" } as never, analysis, "version-91", "printer-91", "pla"), null);
  const loader = studio.slice(
    studio.indexOf("const revision = manufacturingEstimateRevision.current + 1"),
    studio.indexOf("setEngineeringHistory([])"),
  );
  assert.match(loader, /setManufacturingEstimate\(null\)/);
  assert.match(loader, /listManufacturingEstimates\(estimateAnalysis\.id\)/);
  assert.match(loader, /manufacturingEstimateRevision\.current !== revision/);
  assert.match(loader, /manufacturingEstimateContextRef\.current !== context/);
  assert.match(studio, /\[client, estimateAnalysis, activeVersionId, printProfileId, printMaterialId, manufacturingEstimateContext\]/);
});

test("the web card surfaces measured consumables rate inputs recomputed totals and quote boundary", () => {
  assert.match(card, /metrics\.mass_g/);
  assert.match(card, /metrics\.support_mass_g/);
  assert.match(card, /metrics\.layers/);
  assert.match(card, /metrics\.print_time_min/);
  assert.match(card, /metrics\.material_cost/);
  assert.match(card, /metrics\.support_cost/);
  assert.match(card, /metrics\.total_cost/);
  assert.match(card, /Machine rate per hour/);
  assert.match(card, /Printer power, W/);
  assert.match(card, /Electricity rate per kWh/);
  assert.match(card, /Post-processing hours/);
  assert.match(card, /Post-processing rate per hour/);
  assert.match(card, /preview\.machineCost/);
  assert.match(card, /preview\.electricityCost/);
  assert.match(card, /preview\.postprocessCost/);
  assert.match(card, /preview\.totalCost/);
  assert.match(card, /does not present this internal estimate as a supplier quote/);
  assert.match(card, /canCreate \? \(/);
});
