import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { ScanFrame } from "@physical-ai/contracts";

import {
  guidedBrokenPartAngle,
  landedBrokenPartCounts,
} from "../src/lib/broken-part-capture.ts";

const sessionPage = readFileSync(
  new URL("../src/app/scanner/[id]/page.tsx", import.meta.url),
  "utf8",
);
const scannerHome = readFileSync(new URL("../src/app/scanner/page.tsx", import.meta.url), "utf8");

function frame(section: string, sequenceNo: number): ScanFrame {
  return {
    id: `frame-${sequenceNo}`,
    scan_id: "scan-1",
    asset_id: `asset-${sequenceNo}`,
    sequence_no: sequenceNo,
    kind: "rgb",
    pose: { broken_part_section: section },
    quality: {},
    created_at: "2026-11-21T00:00:00Z",
  } as ScanFrame;
}

test("reference 72 coverage counts only frames that the server stored", () => {
  assert.deepEqual(landedBrokenPartCounts([
    frame("whole", 0),
    frame("whole", 1),
    frame("fracture", 2),
    frame("other", 3),
  ]), { whole: 2, fracture: 1, interior: 0 });
});

test("guided angles are bounded deterministic instructions for every section", () => {
  assert.deepEqual(Array.from({ length: 8 }, (_, index) => guidedBrokenPartAngle("whole", index)),
    [0, 45, 90, 135, 180, 225, 270, 315]);
  assert.deepEqual(Array.from({ length: 4 }, (_, index) => guidedBrokenPartAngle("fracture", index)),
    [0, 90, 180, 270]);
  assert.equal(guidedBrokenPartAngle("interior", 4), 0);
});

test("web capture labels commanded guidance separately from metric evidence", () => {
  assert.match(scannerHome, /capture_plan: "broken_part_sections_v1"/);
  assert.match(scannerHome, /camera_pose: "user_confirmed_guided_step"/);
  assert.match(sessionPage, /pose_source: "user_confirmed_guided_step"/);
  assert.match(sessionPage, /position_available: false/);
  assert.match(sessionPage, /metric_scale: "user_measured_max_span"/);
  assert.match(sessionPage, /hidden_geometry: "not_proven"/);
});
