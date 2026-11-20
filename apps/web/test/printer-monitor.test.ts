import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parsePrinterState } from "../src/lib/printer-monitor.ts";

const validState = {
  provider: "octoprint",
  state: "Printing",
  operational: true,
  printing: true,
  paused: false,
  completion_pct: 64,
  elapsed_seconds: 1800,
  remaining_seconds: 1200,
  filename: "villa.gcode",
  nozzle_actual_c: 210,
  nozzle_target_c: 210,
  bed_actual_c: 60,
  bed_target_c: 60,
};

test("printer monitor accepts coherent bounded telemetry from the expected provider", () => {
  assert.deepEqual(parsePrinterState(validState, "octoprint"), validState);
});

test("printer monitor rejects provider substitution and contradictory states", () => {
  assert.equal(parsePrinterState({ ...validState, provider: "stub" }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...validState, paused: true }, "octoprint"), null);
});

test("printer monitor rejects malformed progress, temperatures and durations", () => {
  assert.equal(parsePrinterState({ ...validState, completion_pct: 101 }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...validState, nozzle_actual_c: Number.NaN }, "octoprint"), null);
  assert.equal(parsePrinterState({ ...validState, remaining_seconds: 1.5 }, "octoprint"), null);
});

test("slicer keeps live monitoring independent from a new dispatch and gates controls", () => {
  const page = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");
  assert.match(page, /window\.setInterval\(\(\) => void update\(\), 5000\)/);
  assert.match(page, /window\.setInterval\(\(\) => void updateCamera\(\), 15000\)/);
  assert.match(page, /canEditPrintQueue && bridge\?\.provider === "octoprint" && \(printerState\?\.printing \|\| printerState\?\.paused\)/);
  assert.match(page, /window\.confirm\("Отменить текущую печать\?/);
  assert.match(page, /bridge\.test_mode \|\| !bridge\.has_camera/);
  assert.match(page, /Do not present stale telemetry as the current controller state/);
  assert.match(page, /Do not keep presenting an old frame as a live camera image/);
});
