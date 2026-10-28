import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { verifiedPrintAnalysisJob } from "../src/manufacturing-estimate.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 91 presents only metrics returned by print analysis", () => {
  for (const field of [
    "mass_g",
    "support_mass_g",
    "layers",
    "print_time_min",
    "material_cost",
    "support_cost",
    "total_cost",
    "currency",
  ]) {
    assert.match(project, new RegExp(`report\\.metrics\\.${field}`));
  }
});

test("the estimate uses explicit rates and excludes unsupported manufacturing costs", () => {
  for (const field of [
    "machineHourlyText",
    "printerPowerWText",
    "electricityPerKwhText",
    "postProcessHoursText",
    "postProcessHourlyText",
  ]) {
    assert.match(project, new RegExp(field));
  }
  assert.match(project, /calculateManufacturingEstimate/);
  assert.match(project, /analysisMatchesManufacturingContext/);
  assert.match(project, /\[activeId, printProfileId, printMaterialId\]/);
  assert.match(project, /Для выбранных профиля и материала запустите новую проверку/);
  assert.match(project, /Материалы и время приходят из серверного анализа/);
  assert.match(project, /обслуживание, доставка, налоги и цена подрядчика не включены/);
  assert.match(project, /не выдаёт смету за предложение подрядчика/);
  assert.match(project, /Итого материалов/);
  assert.match(project, /Расчётный итог/);
});

test("O08 accepts only the analysis record created by the exact successful job", () => {
  const context = {
    kind: "analysis",
    project_version_id: "version-8",
    printer_profile_id: "printer-1",
    material_id: "pla",
  };
  const current = { id: "analysis-new", ...context };
  const stale = { id: "analysis-old", ...context };
  const job = {
    type: "analyze_print",
    status: "succeeded",
    project_version_id: "version-8",
    result: { analysis_id: "analysis-new", kind: "analysis" },
  };
  assert.equal(verifiedPrintAnalysisJob(job, [stale, current], "version-8", "printer-1", "pla"), current);
  assert.equal(verifiedPrintAnalysisJob({ ...job, status: "failed" }, [stale, current], "version-8", "printer-1", "pla"), null);
  assert.equal(verifiedPrintAnalysisJob({ ...job, result: { analysis_id: "analysis-old", kind: "analysis" } }, [current], "version-8", "printer-1", "pla"), null);
  assert.match(project, /setAnalysis\(null\)/);
  assert.match(project, /verifiedPrintAnalysisJob\(/);
});
