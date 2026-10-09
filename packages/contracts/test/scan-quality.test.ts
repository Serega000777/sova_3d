import assert from "node:assert/strict";
import test from "node:test";

import { scanFrameWarnings } from "../src/scan-quality.ts";

test("per-frame warnings preserve the exact frame and measured reasons", () => {
  assert.deepEqual(
    scanFrameWarnings([
      { sequence_no: 3, kind: "rgb", quality: { sharpness: 0.2, steady: false } },
      { sequence_no: 1, kind: "rgb", quality: { sharpness: 0.8, steady: true } },
      { sequence_no: 2, kind: "rgb", quality: { sharpness: 0.34, steady: true } },
    ]),
    [
      { sequenceNo: 2, codes: ["blurry"] },
      { sequenceNo: 3, codes: ["blurry", "motion"] },
    ],
  );
});

test("depth frames and unmeasured quality never create invented photo warnings", () => {
  assert.deepEqual(
    scanFrameWarnings([
      { sequence_no: 0, kind: "depth", quality: { sharpness: 0.1, steady: false } },
      { sequence_no: 1, kind: "rgb", quality: {} },
      { sequence_no: 2, kind: "rgb", quality: { sharpness: "0.1", steady: true } },
    ]),
    [],
  );
});

test("malformed sequence and out-of-range or non-finite quality fail closed", () => {
  assert.deepEqual(
    scanFrameWarnings([
      { sequence_no: -1, kind: "rgb", quality: { sharpness: 0.1 } },
      { sequence_no: 1.5, kind: "rgb", quality: { sharpness: 0.1 } },
      { sequence_no: 2, kind: "rgb", quality: { sharpness: -0.1 } },
      { sequence_no: 3, kind: "rgb", quality: { sharpness: Number.NaN } },
    ]),
    [],
  );
});
