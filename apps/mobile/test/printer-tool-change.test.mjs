import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  nextAvailableMaterialSlot,
  validateToolChangeConfig,
} from "../src/printer-tool-change.ts";

const materials = ["pla", "petg"];
const valid = {
  tool_change_mode: "marlin_tn",
  tool_count: 2,
  base_tool: 0,
  purge_tower_enabled: true,
  purge_tower_width_mm: 24,
  purge_volume_mm3: 75,
  material_slots: [
    { slot: 0, material_id: "pla" },
    { slot: 1, material_id: "petg" },
  ],
};

test("valid Generic Marlin capability and disabled inventory follow server parity", () => {
  assert.deepEqual(validateToolChangeConfig(valid, materials, "pla"), {
    ok: true,
    value: valid,
  });

  const disabledInventory = {
    ...valid,
    tool_change_mode: "disabled",
    tool_count: 1,
    base_tool: 15,
    purge_tower_enabled: false,
    material_slots: [
      { slot: 0, material_id: "petg" },
      { slot: 1, material_id: "pla" },
    ],
  };
  assert.deepEqual(validateToolChangeConfig(disabledInventory, materials, "pla"), {
    ok: true,
    value: disabledInventory,
  }, "disabled inventory slots are 0..15 and default need not occupy base_tool");
});

test("default material must be loaded, while base coherence applies only to Marlin", () => {
  assert.equal(validateToolChangeConfig({
    ...valid,
    tool_change_mode: "disabled",
    tool_count: 1,
    purge_tower_enabled: false,
    material_slots: [{ slot: 1, material_id: "petg" }],
  }, materials, "pla").ok, false);

  const marlinFailures = [
    { ...valid, material_slots: [{ slot: 1, material_id: "pla" }] },
    { ...valid, material_slots: [{ slot: 0, material_id: "petg" }, { slot: 1, material_id: "pla" }] },
  ];
  for (const draft of marlinFailures) {
    assert.equal(validateToolChangeConfig(draft, materials, "pla").ok, false);
  }
});

test("slot validation blocks duplicates, schema range errors and unknown materials", () => {
  const cases = [
    { ...valid, material_slots: [...valid.material_slots, { slot: 1, material_id: "pla" }] },
    { ...valid, material_slots: [{ slot: 0, material_id: "pla" }, { slot: 2, material_id: "petg" }] },
    { ...valid, material_slots: [{ slot: 0, material_id: "pla" }, { slot: 1, material_id: "abs" }] },
    { ...valid, material_slots: [{ slot: Number.NaN, material_id: "pla" }] },
    { ...valid, material_slots: [{ slot: Number.POSITIVE_INFINITY, material_id: "pla" }] },
    {
      ...valid,
      tool_change_mode: "disabled",
      purge_tower_enabled: false,
      material_slots: [{ slot: 16, material_id: "pla" }],
    },
  ];
  for (const draft of cases) assert.equal(validateToolChangeConfig(draft, materials, "pla").ok, false);
});

test("numeric capability fields reject non-finite values and enforce inclusive bounds", () => {
  const cases = [
    { ...valid, tool_count: 1, material_slots: [{ slot: 0, material_id: "pla" }] },
    { ...valid, tool_count: Number.NaN },
    { ...valid, tool_count: Number.POSITIVE_INFINITY },
    { ...valid, base_tool: 2 },
    { ...valid, base_tool: Number.NaN },
    { ...valid, base_tool: Number.POSITIVE_INFINITY },
    { ...valid, tool_change_mode: "disabled", purge_tower_enabled: true },
    { ...valid, purge_tower_width_mm: Number.NaN },
    { ...valid, purge_tower_width_mm: Number.POSITIVE_INFINITY },
    { ...valid, purge_tower_width_mm: 9.9 },
    { ...valid, purge_tower_width_mm: 40.1 },
    { ...valid, purge_volume_mm3: Number.NaN },
    { ...valid, purge_volume_mm3: Number.POSITIVE_INFINITY },
    { ...valid, purge_volume_mm3: 9.9 },
    { ...valid, purge_volume_mm3: 500.1 },
  ];
  for (const draft of cases) assert.equal(validateToolChangeConfig(draft, materials, "pla").ok, false);

  assert.equal(validateToolChangeConfig({
    ...valid,
    purge_tower_width_mm: 10,
    purge_volume_mm3: 500,
  }, materials, "pla").ok, true);
  assert.equal(validateToolChangeConfig({
    ...valid,
    purge_tower_width_mm: 40,
    purge_volume_mm3: 10,
  }, materials, "pla").ok, true);
});

test("next free slot search stays bounded for malformed and huge tool counts", () => {
  assert.equal(nextAvailableMaterialSlot("marlin_tn", Number.NaN, []), undefined);
  assert.equal(nextAvailableMaterialSlot("marlin_tn", Number.POSITIVE_INFINITY, []), undefined);
  assert.equal(nextAvailableMaterialSlot("marlin_tn", Number.MAX_SAFE_INTEGER, []), 0);
  assert.equal(nextAvailableMaterialSlot(
    "marlin_tn",
    Number.MAX_SAFE_INTEGER,
    Array.from({ length: 16 }, (_, slot) => ({ slot, material_id: "pla" })),
  ), undefined);
  assert.equal(nextAvailableMaterialSlot("disabled", Number.POSITIVE_INFINITY, [
    { slot: 0, material_id: "pla" },
  ]), 1);
});

test("mobile wiring atomically saves and globally disables every editor while busy", () => {
  const screen = readFileSync(new URL("../app/printers.tsx", import.meta.url), "utf8");
  assert.match(screen, /validateToolChangeConfig/);
  assert.match(screen, /nextAvailableMaterialSlot\(mode, draft\.tool_count, slots\)/);
  assert.doesNotMatch(screen, /Array\.from\(\{ length: Math\.max\(0, count\)/);
  assert.match(screen, /client\.updatePrinterProfile\(profile\.id, \{\s*tool_change_mode:/s);
  assert.match(screen, /material_slots: config\.material_slots/);
  assert.match(screen, /await refresh\(\)/);
  assert.match(screen, /<ToolChangeEditor[\s\S]*disabled=\{Boolean\(busy\)\}[\s\S]*saving=\{busy === profile\.id\}/);
  assert.equal(screen.match(/editable=\{!disabled\}/g)?.length, 5);
  assert.ok((screen.match(/disabled=\{disabled\}/g)?.length ?? 0) >= 4);
  assert.match(screen, /disabled=\{disabled \|\| mode === "disabled"\}/);
  assert.match(screen, /disabled=\{disabled \|\| nextFreeSlot == null \|\| !fallbackMaterialId\}/);
  assert.match(screen, /disabled=\{disabled \|\| !validation\.ok\}/);
  assert.match(screen, /\{saving \? "Сохраняем…" : "Сохранить capability и слоты"\}/);
  assert.match(screen, /Generic Marlin Tn/);
  assert.match(screen, /AMS\/MMU/);
  assert.match(screen, /приёмка на физическом\s+оборудовании не выполнена/);
});
