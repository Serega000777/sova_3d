import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  type PrintFarmPlan,
  type PrintQueue,
} from "@physical-ai/contracts";

import {
  loadPrintQueueSnapshot,
  parsePrintFarmPlan,
  printQueueStorageKey,
  reorderPrintQueuePlate,
  savePrintQueueSnapshot,
  type PrintQueueStorage,
} from "../src/lib/print-queue-snapshot.ts";

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
      {
        number: 1,
        estimated_minutes: 60,
        placements: [{
          version_id: "version-a",
          project_id: "project-a",
          project_name: "A",
          copy_number: 1,
          extents_mm: [10, 20, 30],
          volume_mm3: 6000,
          plate_offset_mm: [5, 6],
          plate_rotation_deg: 0,
          estimated_minutes: 60,
        }],
      },
      {
        number: 2,
        estimated_minutes: 60,
        placements: [{
          version_id: "version-b",
          project_id: "project-b",
          project_name: "B",
          copy_number: 1,
          extents_mm: [20, 10, 30],
          volume_mm3: 6000,
          plate_offset_mm: [7, 8],
          plate_rotation_deg: 90,
          estimated_minutes: 60,
        }],
      },
    ],
  }],
} as PrintFarmPlan;

function queue(nextPlan = plan, revision = 1): PrintQueue {
  return {
    id: "queue-1",
    workspace_id: "workspace-1",
    revision,
    saved_at: `2026-11-05T10:0${revision}:00.000Z`,
    updated_by: "user-1",
    plan: nextPlan,
  };
}

class MemoryStorage implements PrintQueueStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

test("reference 93 saves and restores the canonical plan and validated cache", async () => {
  const storage = new MemoryStorage();
  let remote: PrintQueue | null = null;
  const client = {
    async savePrintQueue(workspaceId: string, nextPlan: PrintFarmPlan, baseRevision: number) {
      assert.equal(workspaceId, "workspace-1");
      assert.equal(baseRevision, 0);
      remote = queue(nextPlan);
      return remote;
    },
    async getPrintQueue() {
      assert.ok(remote);
      return remote;
    },
  };

  const saved = await savePrintQueueSnapshot(client, storage, "workspace-1", plan, 0);
  const loaded = await loadPrintQueueSnapshot(client, storage, "workspace-1");

  assert.equal(saved.status, "saved");
  assert.equal(saved.revision, 1);
  assert.deepEqual(loaded?.plan, plan);
  assert.equal(loaded?.source, "server");
  assert.ok(storage.getItem(printQueueStorageKey("workspace-1")));
});

test("reference 93 reloads the canonical revision after a CAS conflict", async () => {
  const storage = new MemoryStorage();
  const canonical = queue(plan, 3);
  let requestedRevision: number | null = null;
  const client = {
    async savePrintQueue(_workspaceId: string, _plan: PrintFarmPlan, baseRevision: number) {
      requestedRevision = baseRevision;
      throw new ApiError(
        409,
        "conflict",
        "print queue changed on another device",
        { base_revision: baseRevision, current_revision: 3 },
        "trace-1",
      );
    },
    async getPrintQueue() {
      return canonical;
    },
  };

  const result = await savePrintQueueSnapshot(client, storage, "workspace-1", plan, 2);

  assert.equal(requestedRevision, 2);
  assert.equal(result.status, "conflict");
  assert.equal(result.revision, 3);
  assert.deepEqual(result.plan, canonical.plan);
});

test("reference 93 rejects malformed server plans instead of trusting or caching them", async () => {
  const storage = new MemoryStorage();
  const malformed = { ...plan, dispatch_ready: true } as unknown as PrintFarmPlan;
  assert.equal(parsePrintFarmPlan(malformed, "workspace-1"), null);

  await assert.rejects(
    loadPrintQueueSnapshot(
      { async getPrintQueue() { return queue(malformed); } },
      storage,
      "workspace-1",
    ),
    /повреждённый снимок очереди/,
  );
  assert.equal(storage.getItem(printQueueStorageKey("workspace-1")), null);
});

test("reference 93 reorders whole plates without changing placement geometry", () => {
  const before = Object.fromEntries(
    plan.assignments[0]!.plates.map((plate) => [
      plate.placements[0]!.version_id,
      structuredClone(plate.placements[0]),
    ]),
  );

  const reordered = reorderPrintQueuePlate(plan, "printer-1", 1, -1);

  assert.equal(reordered.assignments[0]!.plates[0]!.placements[0]!.version_id, "version-b");
  assert.equal(reordered.assignments[0]!.plates[0]!.number, 1);
  assert.equal(reordered.assignments[0]!.plates[1]!.placements[0]!.version_id, "version-a");
  for (const plate of reordered.assignments[0]!.plates) {
    const placement = plate.placements[0]!;
    assert.deepEqual(placement, before[placement.version_id]);
  }
  assert.equal(plan.assignments[0]!.plates[0]!.placements[0]!.version_id, "version-a");
});
