/**
 * OperationPlan — the only artifact an AI planner is allowed to emit.
 * Mirrors ../operation-plan.schema.json (schema_version 1). Geometry execution
 * never starts while `required_clarifications` is non-empty.
 */
export const OPERATION_PLAN_SCHEMA_VERSION = 1 as const;

export interface Operation {
  /** Operation type from the capability registry, e.g. "create_box". */
  type: string;
  schema_version: number;
  params: Record<string, unknown>;
  /** Entity ids the operation reads or targets (selection scope). */
  entity_refs?: string[];
}

export interface OperationPlan {
  schema_version: typeof OPERATION_PLAN_SCHEMA_VERSION;
  goal: string;
  assumptions?: string[];
  required_clarifications?: string[];
  operations: Operation[];
  validation_steps: string[];
}
