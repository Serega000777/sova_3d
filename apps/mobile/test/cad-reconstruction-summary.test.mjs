import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { cadReconstructionSummaryFromProvenance } from "../src/cad-reconstruction-summary.ts";

test("reads durable Mesh to CAD evidence from immutable version provenance", () => {
  assert.deepEqual(cadReconstructionSummaryFromProvenance({
    operation: "reverse_engineer",
    source_version_id: "source-v1",
    feature_report: {
      planes: [{}, {}, {}],
      cylinders: [{ kind: "hole" }, { kind: "boss" }, { kind: "hole" }],
      patterns: [{}],
      threads: [{}, {}],
      warnings: ["freeform detail omitted", 3],
      reconstruction: { fidelity: "stepped", levels: 4, unexplained_levels: 1 },
    },
    deviation: {
      tolerance_mm: 0.2,
      p95_mm: 0.13,
      max_mm: 0.8,
      within_tolerance: 0.94,
      samples: 3000,
    },
  }), {
    sourceVersionId: "source-v1",
    planeCount: 3,
    holeCount: 2,
    patternCount: 1,
    threadCount: 2,
    fidelity: "stepped",
    levels: 4,
    unexplainedLevels: 1,
    toleranceMm: 0.2,
    p95Mm: 0.13,
    maxMm: 0.8,
    withinTolerance: 0.94,
    samples: 3000,
    warnings: ["freeform detail omitted"],
  });
});

test("fails closed for unrelated or incomplete provenance", () => {
  assert.equal(cadReconstructionSummaryFromProvenance({ operation: "paint" }), null);
  assert.equal(cadReconstructionSummaryFromProvenance({
    operation: "reverse_engineer",
    source_version_id: "source-v1",
    feature_report: { reconstruction: { fidelity: "freeform", levels: 1, unexplained_levels: 1 } },
    deviation: { tolerance_mm: 0.2, p95_mm: Number.NaN, max_mm: 1, within_tolerance: 0.5, samples: 2 },
  }), null);
});

test("project screen exposes recognized features without claiming arbitrary freeform recovery", () => {
  const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  assert.match(source, /Распознанные элементы CAD/);
  assert.match(source, /Свободная и нераспознанная геометрия не достраивалась/);
  assert.match(source, /cadReconstructionSummaryFromProvenance\(active\?\.provenance\)/);
});
