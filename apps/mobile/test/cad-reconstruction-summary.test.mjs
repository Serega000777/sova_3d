import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  cadReconstructionSummaryFromProvenance,
  cadRestorationBoundaryLabel,
} from "../src/cad-reconstruction-summary.ts";

test("reads durable Mesh to CAD evidence from immutable version provenance", () => {
  assert.deepEqual(cadReconstructionSummaryFromProvenance({
    operation: "reverse_engineer",
    source_version_id: "source-v1",
    expected_outputs: ["rebuild_1"],
    bodies: [
      { name: "discarded", bbox_mm: { size: [1, 2, 3] } },
      { name: "rebuild_1", bbox_mm: { size: [120, 40, 60] } },
    ],
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
    restoration: {
      mode: "mirrored_missing_half",
      boundary: "x_max",
      requires_physical_validation: true,
    },
    reinforcement: {
      mode: "thickness_percent",
      percent: 20,
      datum: "minimum_z",
      certified: false,
      requires_physical_validation: true,
    },
  }), {
    sourceVersionId: "source-v1",
    dimensionsMm: [120, 40, 60],
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
    restoration: { boundary: "x_max", requiresPhysicalValidation: true },
    reinforcement: { percent: 20, certified: false, requiresPhysicalValidation: true },
  });
  assert.equal(cadRestorationBoundaryLabel("x_max"), "X+");
});

test("legacy and malformed restoration evidence stays optional and fail-closed", () => {
  const base = {
    operation: "reverse_engineer",
    source_version_id: "source-v1",
    feature_report: { reconstruction: { fidelity: "prismatic", levels: 1, unexplained_levels: 0 } },
    deviation: { tolerance_mm: 0.2, p95_mm: 0.1, max_mm: 0.2, within_tolerance: 1, samples: 500 },
  };
  assert.deepEqual(cadReconstructionSummaryFromProvenance(base)?.restoration, null);
  assert.deepEqual(cadReconstructionSummaryFromProvenance(base)?.dimensionsMm, null);
  assert.deepEqual(cadReconstructionSummaryFromProvenance({
    ...base,
    restoration: { mode: "mirrored_missing_half", boundary: "arbitrary", requires_physical_validation: true },
    reinforcement: { mode: "thickness_percent", percent: 99, datum: "minimum_z", certified: false, requires_physical_validation: true },
  }), { ...cadReconstructionSummaryFromProvenance(base), restoration: null, reinforcement: null });
});

test("trusted output dimensions fail closed for ambiguous or malformed kernel evidence", () => {
  const base = {
    operation: "reverse_engineer",
    source_version_id: "source-v1",
    feature_report: { reconstruction: { fidelity: "prismatic", levels: 1, unexplained_levels: 0 } },
    deviation: { tolerance_mm: 0.2, p95_mm: 0.1, max_mm: 0.2, within_tolerance: 1, samples: 500 },
  };
  assert.equal(cadReconstructionSummaryFromProvenance({
    ...base,
    expected_outputs: ["body", "other"],
    bodies: [{ name: "body", bbox_mm: { size: [120, 40, 60] } }],
  })?.dimensionsMm, null);
  assert.equal(cadReconstructionSummaryFromProvenance({
    ...base,
    expected_outputs: ["body"],
    bodies: [{ name: "body", bbox_mm: { size: [120, 0, 60] } }],
  })?.dimensionsMm, null);
  assert.equal(cadReconstructionSummaryFromProvenance({
    ...base,
    expected_outputs: ["body"],
    bodies: [
      { name: "body", bbox_mm: { size: [120, 40, 60] } },
      { name: "body", bbox_mm: { size: [120, 40, 60] } },
    ],
  })?.dimensionsMm, null);
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
  assert.match(source, /Точные габариты CAD/);
  assert.match(source, /Зеркально восстановлено от границы/);
  assert.match(source, /не сертифицированный расчёт прочности/);
});
