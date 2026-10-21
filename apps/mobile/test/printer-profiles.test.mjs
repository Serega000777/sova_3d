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
