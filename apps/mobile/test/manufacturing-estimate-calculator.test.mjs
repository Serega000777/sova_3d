import assert from "node:assert/strict";
import test from "node:test";

import {
  analysisMatchesManufacturingContext,
  calculateManufacturingEstimate,
  manufacturingEstimateInput,
  restoredManufacturingEstimate,
} from "../src/manufacturing-estimate.ts";

const base = {
  materialTotal: 420,
  printTimeMin: 14 * 60,
  machineHourlyText: "100",
  printerPowerWText: "200",
  electricityPerKwhText: "5",
  postProcessHoursText: "1",
  postProcessHourlyText: "150",
};

test("manufacturing estimate combines measured print facts with explicit user rates", () => {
  const result = calculateManufacturingEstimate(base);
  assert.deepEqual(result, {
    valid: true,
    machineCost: 1400,
    electricityCost: 14,
    postProcessCost: 150,
    total: 1984,
  });
});

test("optional costs remain zero when no user rate is supplied", () => {
  const result = calculateManufacturingEstimate({
    ...base,
    machineHourlyText: "",
    printerPowerWText: "",
    electricityPerKwhText: "",
    postProcessHoursText: "",
    postProcessHourlyText: "",
  });
  assert.deepEqual(result, {
    valid: true,
    machineCost: 0,
    electricityCost: 0,
    postProcessCost: 0,
    total: 420,
  });
});

test("paired costs and numeric bounds fail closed", () => {
  assert.deepEqual(
    calculateManufacturingEstimate({ ...base, electricityPerKwhText: "" }),
    { valid: false, error: "incomplete_electricity" },
  );
  assert.deepEqual(
    calculateManufacturingEstimate({ ...base, postProcessHourlyText: "" }),
    { valid: false, error: "incomplete_post_process" },
  );
  assert.deepEqual(
    calculateManufacturingEstimate({ ...base, machineHourlyText: "-1" }),
    { valid: false, error: "invalid_value" },
  );
});

test("an estimate is bound to the exact version printer profile and material", () => {
  const analysis = {
    kind: "analysis",
    project_version_id: "version-91",
    printer_profile_id: "printer-a",
    material_id: "pla",
  };
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "printer-a", "pla"), true);
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-92", "printer-a", "pla"), false);
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "printer-b", "pla"), false);
  assert.equal(analysisMatchesManufacturingContext(analysis, "version-91", "printer-a", "petg"), false);
  assert.equal(analysisMatchesManufacturingContext({ ...analysis, kind: "optimize" }, "version-91", "printer-a", "pla"), false);
});

test("a persisted estimate restores only when source facts and server totals agree", () => {
  const analysis = {
    id: "analysis-91",
    kind: "analysis",
    project_version_id: "version-91",
    printer_profile_id: "printer-a",
    material_id: "pla",
    report: { metrics: { total_cost: 420, print_time_min: 840 } },
  };
  const saved = {
    id: "estimate-91",
    analysis_id: "analysis-91",
    project_version_id: "version-91",
    printer_profile_id: "printer-a",
    material_id: "pla",
    currency: "RUB",
    material_cost: "420.0000",
    print_time_min: "840.0000",
    machine_rate_per_hour: "100.0000",
    printer_power_w: "200.0000",
    electricity_rate_per_kwh: "5.0000",
    postprocess_hours: "1.0000",
    postprocess_rate_per_hour: "150.0000",
    machine_cost: "1400.00",
    electricity_cost: "14.00",
    postprocess_cost: "150.00",
    total_cost: "1984.00",
    created_at: "2026-11-04T20:00:00Z",
  };
  assert.deepEqual(
    restoredManufacturingEstimate(saved, analysis, "version-91", "printer-a", "pla"),
    {
      input: {
        machine_rate_per_hour: 100,
        printer_power_w: 200,
        electricity_rate_per_kwh: 5,
        postprocess_hours: 1,
        postprocess_rate_per_hour: 150,
      },
      total: 1984,
      createdAt: "2026-11-04T20:00:00Z",
    },
  );
  assert.equal(
    restoredManufacturingEstimate({ ...saved, total_cost: "1985.00" }, analysis, "version-91", "printer-a", "pla"),
    null,
  );
  assert.equal(
    restoredManufacturingEstimate(saved, analysis, "version-92", "printer-a", "pla"),
    null,
  );
});

test("saved-estimate input preserves blank optional rates and complete pairs", () => {
  assert.deepEqual(
    manufacturingEstimateInput({
      machineHourlyText: "",
      printerPowerWText: "",
      electricityPerKwhText: "",
      postProcessHoursText: "",
      postProcessHourlyText: "",
    }),
    {
      machine_rate_per_hour: null,
      printer_power_w: null,
      electricity_rate_per_kwh: null,
      postprocess_hours: null,
      postprocess_rate_per_hour: null,
    },
  );
  assert.equal(
    manufacturingEstimateInput({
      machineHourlyText: "100",
      printerPowerWText: "200",
      electricityPerKwhText: "",
      postProcessHoursText: "1",
      postProcessHourlyText: "150",
    }),
    null,
  );
});
