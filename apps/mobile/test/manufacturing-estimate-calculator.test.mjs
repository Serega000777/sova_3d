import assert from "node:assert/strict";
import test from "node:test";

import {
  analysisMatchesManufacturingContext,
  calculateManufacturingEstimate,
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
