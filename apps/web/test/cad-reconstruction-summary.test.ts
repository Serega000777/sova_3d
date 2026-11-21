import assert from "node:assert/strict";
import test from "node:test";

import { cadReconstructionSummaryForVersion } from "../src/lib/cad-reconstruction-summary.ts";

function version(overrides: Record<string, unknown> = {}) {
  return {
    parent_version_id: "source-version",
    provenance: {
      operation: "reverse_engineer",
      source_version_id: "source-version",
      expected_outputs: ["body"],
      bodies: [{ name: "body", valid: true, bbox_mm: { size: [40, 20, 8] } }],
      feature_report: {
        ok: true,
        faces: 18,
        watertight: true,
        planes: [{}, {}],
        cylinders: [{ kind: "hole" }, { kind: "boss" }],
        patterns: [{}],
        threads: [{}, {}],
        warnings: ["bounded reconstruction", 42],
        reconstruction: { fidelity: "prismatic", levels: 2, unexplained_levels: 0 },
      },
      deviation: {
        tolerance_mm: 0.2,
        mean_mm: 0.03,
        p95_mm: 0.08,
        max_mm: 0.15,
        within_tolerance: 0.99,
        samples: 3000,
      },
      ...overrides,
    },
  };
}

test("restores the exact persisted Mesh to CAD report from immutable provenance", () => {
  assert.deepEqual(cadReconstructionSummaryForVersion(version()), {
    sourceVersionId: "source-version",
    dimensionsMm: [40, 20, 8],
    faceCount: 18,
    watertight: true,
    planeCount: 2,
    holeCount: 1,
    patternCount: 1,
    threadCount: 2,
    fidelity: "prismatic",
    levels: 2,
    unexplainedLevels: 0,
    toleranceMm: 0.2,
    meanMm: 0.03,
    p95Mm: 0.08,
    maxMm: 0.15,
    withinTolerance: 0.99,
    samples: 3000,
    warnings: ["bounded reconstruction"],
  });
});

test("fails closed for a substituted parent or malformed measured report", () => {
  assert.equal(cadReconstructionSummaryForVersion({ ...version(), parent_version_id: "other" }), null);
  assert.equal(cadReconstructionSummaryForVersion(version({
    deviation: { tolerance_mm: 0.2, mean_mm: 0.03, p95_mm: 0.08, max_mm: 0.15, within_tolerance: 1.2, samples: 3000 },
  })), null);
  assert.equal(cadReconstructionSummaryForVersion(version({ operation: "repair_mesh" })), null);
});

test("hides ambiguous, invalid and legacy kernel dimensions without discarding the report", () => {
  for (const bodies of [
    [{ name: "body", valid: false, bbox_mm: { size: [40, 20, 8] } }],
    [{ name: "body", valid: true, bbox_mm: { size: [40, 20, 8] } }, { name: "body", valid: true, bbox_mm: { size: [1, 1, 1] } }],
    [{ name: "body", valid: true, bbox_mm: { size: [40, 0, 8] } }],
  ]) {
    assert.equal(cadReconstructionSummaryForVersion(version({ bodies }))?.dimensionsMm, null);
  }
});
