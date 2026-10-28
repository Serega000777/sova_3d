import type { PrinterState } from "@physical-ai/contracts";

function nullableNumber(value: unknown, minimum: number, maximum: number): value is number | null {
  return value === null
    || (typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum);
}

function nullableSeconds(value: unknown): value is number | null {
  return value === null
    || (typeof value === "number" && Number.isInteger(value) && value >= 0);
}

/** Fail closed on malformed or cross-provider controller telemetry. */
export function parsePrinterState(
  value: unknown,
  expectedProvider: "stub" | "octoprint",
): PrinterState | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const state = value as Record<string, unknown>;
  if (
    state.provider !== expectedProvider
    || typeof state.state !== "string"
    || state.state.trim() === ""
    || typeof state.operational !== "boolean"
    || typeof state.printing !== "boolean"
    || typeof state.paused !== "boolean"
    || (state.printing && state.paused)
    || !(state.filename === null || typeof state.filename === "string")
    || !nullableNumber(state.completion_pct, 0, 100)
    || !nullableSeconds(state.elapsed_seconds)
    || !nullableSeconds(state.remaining_seconds)
    || !nullableNumber(state.nozzle_actual_c, -100, 1000)
    || !nullableNumber(state.nozzle_target_c, 0, 1000)
    || !nullableNumber(state.bed_actual_c, -100, 1000)
    || !nullableNumber(state.bed_target_c, 0, 1000)
  ) return null;
  return value as PrinterState;
}
