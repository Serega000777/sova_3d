import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/printer-calibration/[id].tsx", import.meta.url), "utf8");
const printers = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");

test("reference 56 is reachable from each real printer profile", () => {
  assert.match(printers, /router\.push\(`\/printer-calibration\/\$\{profile\.id\}`\)/);
  assert.match(screen, /образец → измерения → результат/);
});

test("calibration creates a coupon project and accepts only a succeeded job", () => {
  assert.match(screen, /client\.startCalibrationPrint\(profile\.id\)/);
  assert.match(screen, /client\.waitForJob\(started\.job\.job_id\)/);
  assert.match(screen, /job\.status !== "succeeded"/);
  assert.match(screen, /router\.push\(`\/project\/\$\{projectId\}`\)/);
  assert.match(screen, /не запускает физический принтер и не отправляет G-code автоматически/);
});

test("caliper readings are sparse, validated and recorded through the typed API", () => {
  assert.match(screen, /const measurements: CalibrationMeasurements = \{\}/);
  assert.match(screen, /!Number\.isFinite\(parsed\) \|\| parsed <= 0/);
  assert.match(screen, /Object\.keys\(measurements\)\.length === 0/);
  assert.match(screen, /client\.recordCalibration\(profile\.id, measurements\)/);
});

test("learned values remain distinct and affect only future preparation", () => {
  for (const key of ["hole_undersize_mm", "peg_oversize_mm", "xy_compensation_mm", "shrinkage_pct", "flow_pct"]) {
    assert.match(screen, new RegExp(key));
  }
  assert.match(screen, /будущей подготовке печати/);
  assert.match(screen, /не исправляют уже созданный G-code/);
});
