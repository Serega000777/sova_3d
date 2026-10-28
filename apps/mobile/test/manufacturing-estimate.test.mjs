import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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
