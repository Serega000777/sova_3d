/** The stage a scan is in, read from the status the API reports. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { SCAN_STAGE_COUNT, scanStage } from "../src/scan-stages.ts";

test("each real scan status maps to a stage, in order", () => {
  assert.deepEqual(
    ["capturing", "uploading", "reconstructing", "paused", "ready", "accepted"].map(scanStage),
    [0, 0, 1, 1, 2, 3],
  );
  assert.equal(SCAN_STAGE_COUNT, 4);
});

test("a failed, cancelled or unknown scan has no current stage", () => {
  for (const status of ["failed", "canceled", "something_new", ""]) assert.equal(scanStage(status), null);
});
