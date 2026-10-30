import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildMaterialSlotsUpdate,
  buildPrinterProfileCreatePayload,
} from "../src/lib/printer-profile-payload.ts";

test("profile creation sets a default material without inferring loaded inventory", () => {
  const payload = buildPrinterProfileCreatePayload({
    workspaceId: "workspace-1",
    printerModelId: "printer-model-1",
    name: "Workshop printer",
    defaultMaterialId: "pla",
    isDefault: true,
  });

  assert.deepEqual(payload, {
    workspace_id: "workspace-1",
    printer_model_id: "printer-model-1",
    name: "Workshop printer",
    default_material_id: "pla",
    is_default: true,
  });
  assert.equal(Object.hasOwn(payload, "material_slots"), false);
});

test("explicit loaded-slot save still sends material_slots", () => {
  const slots = [
    { slot: 0, material_id: "pla" },
    { slot: 2, material_id: "petg" },
  ];
  assert.deepEqual(buildMaterialSlotsUpdate(slots), {
    material_slots: slots,
  });

  const page = readFileSync(new URL("../src/app/printers/page.tsx", import.meta.url), "utf8");
  assert.match(
    page,
    /createPrinterProfile\(buildPrinterProfileCreatePayload\(\{/,
  );
  assert.match(
    page,
    /updatePrinterProfile\(profile\.id, buildMaterialSlotsUpdate\(slots\)\)/,
  );
  assert.match(page, /Add loaded slot/);
  assert.match(page, /Save slots/);
});
