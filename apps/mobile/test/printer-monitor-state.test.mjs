import assert from "node:assert/strict";
import test from "node:test";

import { parsePrinterState } from "../src/printer-monitor.ts";

const state = {
  provider: "octoprint",
  state: "Printing",
  operational: true,
  printing: true,
  paused: false,
  completion_pct: 42.5,
  elapsed_seconds: 120,
  remaining_seconds: 180,
  filename: "part.gcode",
  nozzle_actual_c: 210,
  nozzle_target_c: 210,
  bed_actual_c: 60,
  bed_target_c: 60,
};

test("reference 95 accepts only coherent telemetry from the configured provider", () => {
  assert.equal(parsePrinterState(state, "octoprint"), state);
  assert.equal(parsePrinterState(state, "stub"), null);
  assert.equal(parsePrinterState({ ...state, completion_pct: Number.NaN }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...state, completion_pct: 101 }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...state, printing: true, paused: true }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...state, elapsed_seconds: -1 }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...state, nozzle_actual_c: 5000 }, "octoprint"), null);
});
