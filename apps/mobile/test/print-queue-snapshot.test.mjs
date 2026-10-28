import assert from "node:assert/strict";
import test from "node:test";

import {
  parsePrintQueueSnapshot,
  parsePrintFarmPlan,
  printQueueSnapshot,
  printQueueStorageKey,
  reorderPrintQueuePlate,
} from "../src/print-queue-snapshot.ts";

const plan = {
  workspace_id: "workspace-1",
  material_id: "pla",
  currency: "RUB",
  settings: {},
  item_count: 2,
  plate_count: 2,
  estimated_makespan_minutes: 120,
  estimated_material_g: 10,
  estimated_material_cost: 20,
  dispatch_ready: false,
  assignments: [{
    printer_profile_id: "printer-1",
    printer_name: "Printer",
    bed_mm: [200, 200, 200],
    estimated_minutes: 120,
    plates: [
      { number: 1, estimated_minutes: 60, placements: [{ version_id: "a", project_id: "pa", project_name: "A", copy_number: 1, extents_mm: [10, 20, 30], volume_mm3: 6000, plate_offset_mm: [5, 5], plate_rotation_deg: 0, estimated_minutes: 60 }] },
      { number: 2, estimated_minutes: 60, placements: [{ version_id: "b", project_id: "pb", project_name: "B", copy_number: 1, extents_mm: [20, 10, 30], volume_mm3: 6000, plate_offset_mm: [5, 5], plate_rotation_deg: 90, estimated_minutes: 60 }] },
    ],
  }],
};

test("print queue snapshot is workspace-bound and restores a server plan", () => {
  const snapshot = printQueueSnapshot("workspace-1", plan, "2026-10-27T08:00:00.000Z");
  assert.equal(printQueueStorageKey("workspace-1"), "sova:print-queue:v1:workspace-1");
  assert.deepEqual(parsePrintQueueSnapshot(JSON.stringify(snapshot), "workspace-1"), snapshot);
  assert.equal(parsePrintQueueSnapshot(JSON.stringify(snapshot), "workspace-2"), null);
});

test("malformed, dispatch-ready and inconsistent plate snapshots fail closed", () => {
  assert.equal(parsePrintQueueSnapshot("not-json", "workspace-1"), null);
  assert.equal(parsePrintQueueSnapshot(JSON.stringify(printQueueSnapshot("workspace-1", { ...plan, dispatch_ready: true })), "workspace-1"), null);
  assert.equal(parsePrintQueueSnapshot(JSON.stringify(printQueueSnapshot("workspace-1", { ...plan, plate_count: 3 })), "workspace-1"), null);
  assert.equal(parsePrintFarmPlan({ ...plan, currency: "rub" }, "workspace-1"), null);
  assert.equal(parsePrintFarmPlan({ ...plan, estimated_material_cost: Number.NaN }, "workspace-1"), null);
  const outOfBed = structuredClone(plan);
  outOfBed.assignments[0].plates[0].placements[0].plate_offset_mm = [195, 5];
  assert.equal(parsePrintFarmPlan(outOfBed, "workspace-1"), null);
  const duplicatePrinter = structuredClone(plan);
  duplicatePrinter.assignments.push(structuredClone(plan.assignments[0]));
  assert.equal(parsePrintFarmPlan(duplicatePrinter, "workspace-1"), null);
});

test("plate priority changes order without changing placement geometry", () => {
  const reordered = reorderPrintQueuePlate(plan, "printer-1", 1, -1);
  assert.equal(reordered.assignments[0].plates[0].placements[0].version_id, "b");
  assert.equal(reordered.assignments[0].plates[0].number, 1);
  assert.equal(reordered.assignments[0].plates[1].placements[0].version_id, "a");
  assert.equal(plan.assignments[0].plates[0].placements[0].version_id, "a");
});
