import type { PrintFarmPlan } from "@physical-ai/contracts";

export const PRINT_QUEUE_SNAPSHOT_VERSION = 1 as const;

export interface PrintQueueSnapshot {
  schema_version: typeof PRINT_QUEUE_SNAPSHOT_VERSION;
  workspace_id: string;
  saved_at: string;
  plan: PrintFarmPlan;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
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
    const plan = record(root?.plan);
    const assignments = plan?.assignments;
    if (
      root?.schema_version !== PRINT_QUEUE_SNAPSHOT_VERSION ||
      root.workspace_id !== workspaceId ||
      typeof root.saved_at !== "string" ||
      !Number.isFinite(Date.parse(root.saved_at)) ||
      plan?.workspace_id !== workspaceId ||
      plan.dispatch_ready !== false ||
      !Number.isInteger(plan.item_count) ||
      (plan.item_count as number) < 1 ||
      (plan.item_count as number) > 100 ||
      !Number.isInteger(plan.plate_count) ||
      (plan.plate_count as number) < 1 ||
      (plan.plate_count as number) > 100 ||
      !Array.isArray(assignments) ||
      assignments.length < 1 ||
      assignments.length > 50
    ) return null;
    let plateCount = 0;
    for (const assignmentValue of assignments) {
      const assignment = record(assignmentValue);
      if (typeof assignment?.printer_profile_id !== "string" || !Array.isArray(assignment.plates)) {
        return null;
      }
      for (const plateValue of assignment.plates) {
        const plate = record(plateValue);
        if (!plate || !Array.isArray(plate.placements) || plate.placements.length < 1) return null;
        plateCount += 1;
      }
    }
    if (plateCount !== plan.plate_count) return null;
    return root as unknown as PrintQueueSnapshot;
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

export function reorderPrintQueuePlate(
  plan: PrintFarmPlan,
  printerProfileId: string,
  plateIndex: number,
  direction: -1 | 1,
): PrintFarmPlan {
  const assignments = plan.assignments.map((assignment) => {
    if (assignment.printer_profile_id !== printerProfileId) return assignment;
    const target = plateIndex + direction;
    if (plateIndex < 0 || plateIndex >= assignment.plates.length || target < 0 || target >= assignment.plates.length) {
      return assignment;
    }
    const plates = [...assignment.plates];
    [plates[plateIndex], plates[target]] = [plates[target]!, plates[plateIndex]!];
    return {
      ...assignment,
      plates: plates.map((plate, index) => ({ ...plate, number: index + 1 })),
    };
  });
  return { ...plan, assignments };
}
