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

test("the estimate explicitly excludes unsupported manufacturing costs", () => {
  assert.match(project, /Работа принтера, электричество, обслуживание, постобработка, доставка и цена подрядчика не включены/);
  assert.match(project, /Итого материалов/);
});
