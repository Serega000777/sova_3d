import assert from "node:assert/strict";
import test from "node:test";

import {
  assignableProcessMaterialSlots,
  sanitizeProcessMaterialAssignments,
} from "../src/lib/process-material-slots.ts";

const slots = [
  { slot: 0, material_id: "pla" },
  { slot: 1, material_id: "petg" },
];

test("disabled tool changes expose only a matching base slot", () => {
  const profile = {
    material_slots: slots,
    tool_change_mode: "disabled" as const,
    base_tool: 0,
  };

  assert.deepEqual(assignableProcessMaterialSlots(profile, "pla"), [slots[0]]);
  assert.deepEqual(assignableProcessMaterialSlots(profile, "petg"), []);
});

test("Marlin Tn keeps all loaded material slots available", () => {
  assert.deepEqual(
    assignableProcessMaterialSlots(
      { material_slots: slots, tool_change_mode: "marlin_tn", base_tool: 0 },
      "pla",
    ),
    slots,
  );
});

test("Marlin Tn fails closed on a base-material mismatch and clears prior assignments", () => {
  const assignable = assignableProcessMaterialSlots(
    { material_slots: slots, tool_change_mode: "marlin_tn", base_tool: 0 },
    "petg",
  );

  assert.deepEqual(assignable, []);
  assert.deepEqual(
    sanitizeProcessMaterialAssignments([{ material_slot: 1, operation: "painted" }], assignable),
    [{ material_slot: null, operation: "painted" }],
  );
});

test("a base-tool change clears stale assignments until the selected material matches", () => {
  const changedProfile = {
    material_slots: slots,
    tool_change_mode: "marlin_tn" as const,
    base_tool: 1,
  };
  const mismatched = assignableProcessMaterialSlots(changedProfile, "pla");

  assert.deepEqual(mismatched, []);
  assert.deepEqual(
    sanitizeProcessMaterialAssignments([{ material_slot: 0, operation: "painted" }], mismatched),
    [{ material_slot: null, operation: "painted" }],
  );
  assert.deepEqual(assignableProcessMaterialSlots(changedProfile, "petg"), slots);
});

test("stale painted assignments become inherit without losing operation parameters", () => {
  const modifiers = [
    {
      material_slot: 0,
      infill_density_pct: 30,
      print_speed_pct: 90,
      region: { kind: "box", min_mm: [0, 0, 0], max_mm: [1, 1, 1] },
    },
    {
      material_slot: 1,
      infill_density_pct: 70,
      print_speed_pct: 120,
      region: { kind: "box", min_mm: [1, 1, 1], max_mm: [2, 2, 2] },
    },
    {
      material_slot: null,
      infill_density_pct: 50,
      print_speed_pct: 100,
      region: { kind: "box", min_mm: [2, 2, 2], max_mm: [3, 3, 3] },
    },
  ];

  const sanitized = sanitizeProcessMaterialAssignments(modifiers, [slots[0]]);

  assert.deepEqual(sanitized, [
    modifiers[0],
    { ...modifiers[1], material_slot: null },
    modifiers[2],
  ]);
  assert.equal(sanitized[0], modifiers[0]);
  assert.equal(sanitized[2], modifiers[2]);
  assert.equal(modifiers[1].material_slot, 1);
});
