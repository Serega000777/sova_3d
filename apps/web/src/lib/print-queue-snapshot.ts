import {
  ApiError,
  type PrintFarmPlan,
  type PrintQueue,
} from "@physical-ai/contracts";

export const PRINT_QUEUE_SNAPSHOT_VERSION = 1 as const;

export interface PrintQueueSnapshot {
  schema_version: typeof PRINT_QUEUE_SNAPSHOT_VERSION;
  workspace_id: string;
  saved_at: string;
  plan: PrintFarmPlan;
}

export interface PrintQueueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface PrintQueueClient {
  getPrintQueue(workspaceId: string): Promise<PrintQueue>;
  savePrintQueue(
    workspaceId: string,
    plan: PrintFarmPlan,
    baseRevision: number,
  ): Promise<PrintQueue>;
}

export interface LoadedPrintQueue {
  plan: PrintFarmPlan;
  revision: number;
  savedAt: string;
  source: "server" | "cache";
}

export type SavedPrintQueue = LoadedPrintQueue & {
  status: "saved" | "conflict";
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function finite(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= minimum;
}

function vector(value: unknown, length: number, minimum = 0): value is number[] {
  return Array.isArray(value)
    && value.length === length
    && value.every((item) => finite(item, minimum));
}

/** Validate every field and placement bound before displaying or caching a queue plan. */
export function parsePrintFarmPlan(value: unknown, workspaceId: string): PrintFarmPlan | null {
  const plan = record(value);
  const assignments = plan?.assignments;
  if (
    plan?.workspace_id !== workspaceId
    || plan.dispatch_ready !== false
    || typeof plan.material_id !== "string"
    || plan.material_id.trim() === ""
    || typeof plan.currency !== "string"
    || !/^[A-Z]{3}$/.test(plan.currency)
    || !record(plan.settings)
    || !Object.values(plan.settings as Record<string, unknown>).every((item) => finite(item))
    || !Number.isInteger(plan.item_count)
    || (plan.item_count as number) < 1
    || (plan.item_count as number) > 100
    || !Number.isInteger(plan.plate_count)
    || (plan.plate_count as number) < 1
    || (plan.plate_count as number) > 100
    || !finite(plan.estimated_makespan_minutes)
    || !finite(plan.estimated_material_g)
    || !finite(plan.estimated_material_cost)
    || !Array.isArray(assignments)
    || assignments.length < 1
    || assignments.length > 20
  ) return null;

  let plateCount = 0;
  let itemCount = 0;
  const printerIds = new Set<string>();
  const copies = new Set<string>();
  for (const assignmentValue of assignments) {
    const assignment = record(assignmentValue);
    if (
      typeof assignment?.printer_profile_id !== "string"
      || assignment.printer_profile_id.trim() === ""
      || printerIds.has(assignment.printer_profile_id)
      || typeof assignment.printer_name !== "string"
      || assignment.printer_name.trim() === ""
      || !vector(assignment.bed_mm, 3, Number.EPSILON)
      || !finite(assignment.estimated_minutes)
      || !Array.isArray(assignment.plates)
      || assignment.plates.length < 1
      || assignment.plates.length > 100
    ) return null;
    printerIds.add(assignment.printer_profile_id);
    const bed = assignment.bed_mm;
    for (let plateIndex = 0; plateIndex < assignment.plates.length; plateIndex += 1) {
      const plate = record(assignment.plates[plateIndex]);
      if (
        plate?.number !== plateIndex + 1
        || !finite(plate.estimated_minutes)
        || !Array.isArray(plate.placements)
        || plate.placements.length < 1
        || plate.placements.length > 100
      ) return null;
      plateCount += 1;
      for (const placementValue of plate.placements) {
        const placement = record(placementValue);
        if (
          typeof placement?.version_id !== "string"
          || placement.version_id.trim() === ""
          || typeof placement.project_id !== "string"
          || placement.project_id.trim() === ""
          || typeof placement.project_name !== "string"
          || placement.project_name.trim() === ""
          || !Number.isInteger(placement.copy_number)
          || (placement.copy_number as number) < 1
          || (placement.copy_number as number) > 50
          || !vector(placement.extents_mm, 3, Number.EPSILON)
          || !finite(placement.volume_mm3, Number.EPSILON)
          || !vector(placement.plate_offset_mm, 2)
          || !(placement.plate_rotation_deg === 0 || placement.plate_rotation_deg === 90)
          || !finite(placement.estimated_minutes)
        ) return null;
        const copyKey = `${placement.version_id}:${placement.copy_number}`;
        if (copies.has(copyKey)) return null;
        copies.add(copyKey);
        const width = placement.extents_mm[placement.plate_rotation_deg === 90 ? 1 : 0]!;
        const depth = placement.extents_mm[placement.plate_rotation_deg === 90 ? 0 : 1]!;
        if (
          placement.plate_offset_mm[0]! + width > bed[0]!
          || placement.plate_offset_mm[1]! + depth > bed[1]!
          || placement.extents_mm[2]! > bed[2]!
        ) return null;
        itemCount += 1;
      }
    }
  }
  return plateCount === plan.plate_count && itemCount === plan.item_count
    ? value as PrintFarmPlan
    : null;
}

export function printQueueStorageKey(workspaceId: string): string {
  return `sova:print-queue:v1:${workspaceId}`;
}

export function parsePrintQueueSnapshot(
  raw: string | null,
  workspaceId: string,
): PrintQueueSnapshot | null {
  if (!raw) return null;
  try {
    const root = record(JSON.parse(raw));
    const plan = parsePrintFarmPlan(root?.plan, workspaceId);
    if (
      root?.schema_version !== PRINT_QUEUE_SNAPSHOT_VERSION
      || root.workspace_id !== workspaceId
      || typeof root.saved_at !== "string"
      || !Number.isFinite(Date.parse(root.saved_at))
      || !plan
    ) return null;
    return { ...root, plan } as unknown as PrintQueueSnapshot;
  } catch {
    return null;
  }
}

export function printQueueSnapshot(
  workspaceId: string,
  plan: PrintFarmPlan,
  savedAt = new Date().toISOString(),
): PrintQueueSnapshot {
  return {
    schema_version: PRINT_QUEUE_SNAPSHOT_VERSION,
    workspace_id: workspaceId,
    saved_at: savedAt,
    plan,
  };
}

function cacheSnapshot(
  storage: PrintQueueStorage,
  workspaceId: string,
  plan: PrintFarmPlan,
  savedAt: string,
): void {
  try {
    storage.setItem(
      printQueueStorageKey(workspaceId),
      JSON.stringify(printQueueSnapshot(workspaceId, plan, savedAt)),
    );
  } catch {
    // The canonical server snapshot still works when browser storage is unavailable.
  }
}

function verifiedRemote(remote: PrintQueue, workspaceId: string): LoadedPrintQueue {
  const plan = parsePrintFarmPlan(remote.plan, workspaceId);
  if (!plan) throw new Error("Сервер вернул повреждённый снимок очереди.");
  return {
    plan,
    revision: remote.revision,
    savedAt: remote.saved_at,
    source: "server",
  };
}

/** Restore the shared server revision, using only a fully validated cache while offline. */
export async function loadPrintQueueSnapshot(
  client: Pick<PrintQueueClient, "getPrintQueue">,
  storage: PrintQueueStorage,
  workspaceId: string,
): Promise<LoadedPrintQueue | null> {
  try {
    const loaded = verifiedRemote(await client.getPrintQueue(workspaceId), workspaceId);
    cacheSnapshot(storage, workspaceId, loaded.plan, loaded.savedAt);
    return loaded;
  } catch (reason) {
    // A malformed server response must fail closed rather than falling back to older data.
    if (reason instanceof Error && reason.message === "Сервер вернул повреждённый снимок очереди.") {
      throw reason;
    }
    let raw: string | null = null;
    try {
      raw = storage.getItem(printQueueStorageKey(workspaceId));
    } catch {
      // Browser storage may be disabled.
    }
    const cached = parsePrintQueueSnapshot(raw, workspaceId);
    return cached
      ? { plan: cached.plan, revision: 0, savedAt: cached.saved_at, source: "cache" }
      : null;
  }
}

export function isPrintQueueConflict(reason: unknown): boolean {
  return reason instanceof ApiError && reason.status === 409;
}

/** Save with CAS; on conflict return the freshly reloaded canonical server revision. */
export async function savePrintQueueSnapshot(
  client: PrintQueueClient,
  storage: PrintQueueStorage,
  workspaceId: string,
  plan: PrintFarmPlan,
  baseRevision: number,
): Promise<SavedPrintQueue> {
  try {
    const saved = verifiedRemote(
      await client.savePrintQueue(workspaceId, plan, baseRevision),
      workspaceId,
    );
    cacheSnapshot(storage, workspaceId, saved.plan, saved.savedAt);
    return { ...saved, status: "saved" };
  } catch (reason) {
    if (!isPrintQueueConflict(reason)) throw reason;
    const canonical = verifiedRemote(await client.getPrintQueue(workspaceId), workspaceId);
    cacheSnapshot(storage, workspaceId, canonical.plan, canonical.savedAt);
    return { ...canonical, status: "conflict" };
  }
}

export function reorderPrintQueuePlate(
  plan: PrintFarmPlan,
  printerProfileId: string,
  plateIndex: number,
  direction: -1 | 1,
): PrintFarmPlan {
  const assignments = plan.assignments.map((assignment) => {
    if (assignment.printer_profile_id !== printerProfileId) return assignment;
    const target = plateIndex + direction;
    if (
      plateIndex < 0
      || plateIndex >= assignment.plates.length
      || target < 0
      || target >= assignment.plates.length
    ) return assignment;
    const plates = [...assignment.plates];
    [plates[plateIndex], plates[target]] = [plates[target]!, plates[plateIndex]!];
    return {
      ...assignment,
      plates: plates.map((plate, index) => ({ ...plate, number: index + 1 })),
    };
  });
  return { ...plan, assignments };
}
