import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");
const profile = readFileSync(new URL("../app/(tabs)/profile.tsx", import.meta.url), "utf8");

test("reference 55 is reachable from the mobile profile tab", () => {
  assert.match(profile, /router\.push\("\/printers"\)/);
  assert.match(screen, /Профили принтеров/);
});

test("mobile printer profiles use the shared workspace API", () => {
  assert.match(screen, /client\.listPrinterProfiles\(session\.workspaceId\)/);
  assert.match(screen, /client\.listPrinterModels\(\)/);
  assert.match(screen, /client\.listMaterials\(\)/);
  assert.match(screen, /client\.createPrinterProfile\(\{/);
  assert.match(screen, /workspace_id: session\.workspaceId/);
  assert.match(screen, /client\.updatePrinterProfile\(profile\.id, \{ is_default: true \}\)/);
});

test("printer profile shows effective print parameters", () => {
  assert.match(screen, /profile\.nozzle_mm \?\? model\?\.nozzle_mm/);
  assert.match(screen, /profile\.default_material_id/);
  assert.match(screen, /profile\.layer_height_mm/);
});

test("mobile saves one bounded raft density pair in the shared typed profile map", () => {
  assert.match(screen, /profile\.raft_density_profiles\[selected\]/);
  assert.match(screen, /baseNumber >= 10 && baseNumber <= 70/);
  assert.match(screen, /faceNumber >= 50 && faceNumber <= 100/);
  assert.match(screen, /client\.updatePrinterProfile\(profile\.id, \{/);
  assert.match(screen, /raft_density_profiles:/);
  assert.match(screen, /base_density_pct: base, interface_density_pct: face/);
  assert.match(screen, /Без настройки сохраняется прежний шаг: основа 40%, интерфейс 100%/);
});

test("alternate reference 55/02 shows the canonical build volume without claiming printer readiness", () => {
  assert.match(screen, /model\.bed_x_mm/);
  assert.match(screen, /model\.bed_y_mm/);
  assert.match(screen, /model\.bed_z_mm/);
  assert.match(screen, /Рабочий объём/);
  assert.match(screen, /profile\.is_default \? "По умолчанию" : "Профиль"/);
  assert.doesNotMatch(screen, /profile\.is_default \? "По умолчанию" : "Готов"/);
});
