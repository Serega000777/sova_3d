import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isScanDerivedVersion,
  parseMeshRepairJobResult,
  parseMeshRepairReport,
  type VersionLineageNode,
} from "../src/repair.ts";

const report = {
  changed: true,
  before: { holes: 3, bodies: 4 },
  after: { holes: 1, bodies: 2 },
  delta: { holes_closed: 2, bodies_removed: 2 },
  fragment_max_size_mm: 4.5,
};

test("repair report exposes exact before/after hole and fragment counts", () => {
  assert.deepEqual(parseMeshRepairReport(report), {
    changed: true,
    before: { holes: 3, fragments: 4 },
    after: { holes: 1, fragments: 2 },
    holesClosed: 2,
    fragmentsRemoved: 2,
    fragmentMaxSizeMm: 4.5,
  });
  assert.deepEqual(
    parseMeshRepairJobResult({ version_id: "new", source_version_id: "old", report }),
    {
      versionId: "new",
      sourceVersionId: "old",
      report: {
        changed: true,
        before: { holes: 3, fragments: 4 },
        after: { holes: 1, fragments: 2 },
        holesClosed: 2,
        fragmentsRemoved: 2,
        fragmentMaxSizeMm: 4.5,
      },
    },
  );
});

test("repair report parsing fails closed on partial or forged counters", () => {
  assert.equal(parseMeshRepairReport({ ...report, before: { holes: 3 } }), null);
  assert.equal(parseMeshRepairReport({ ...report, after: { holes: -1, bodies: 2 } }), null);
  assert.equal(parseMeshRepairReport({ ...report, delta: { holes_closed: 1.5 } }), null);
  assert.equal(
    parseMeshRepairReport({ ...report, delta: { holes_closed: 2, bodies_removed: -1 } }),
    null,
  );
  assert.equal(parseMeshRepairReport({ ...report, fragment_max_size_mm: "4.5" }), null);
  assert.equal(parseMeshRepairJobResult({ version_id: "new", report }), null);
});

test("legacy repair reports remain readable without fragment-cleanup fields", () => {
  assert.deepEqual(
    parseMeshRepairReport({
      changed: false,
      before: { holes: 0, bodies: 1 },
      after: { holes: 0, bodies: 1 },
      delta: { holes_closed: 0 },
    }),
    {
      changed: false,
      before: { holes: 0, fragments: 1 },
      after: { holes: 0, fragments: 1 },
      holesClosed: 0,
      fragmentsRemoved: 0,
      fragmentMaxSizeMm: null,
    },
  );
});

test("scan ancestry stays repairable through immutable children and rejects cycles", () => {
  const scan: VersionLineageNode = {
    id: "scan",
    parent_version_id: null,
    provenance: { operation: "scan" },
  };
  const repaired: VersionLineageNode = {
    id: "repair",
    parent_version_id: "scan",
    provenance: { operation: "repair" },
  };
  assert.equal(isScanDerivedVersion(repaired, [repaired, scan]), true);
  assert.equal(
    isScanDerivedVersion(
      { id: "generated", parent_version_id: null, provenance: { operation: "generate" } },
      [scan],
    ),
    false,
  );
  const cycleA: VersionLineageNode = { id: "a", parent_version_id: "b", provenance: {} };
  const cycleB: VersionLineageNode = { id: "b", parent_version_id: "a", provenance: {} };
  assert.equal(isScanDerivedVersion(cycleA, [cycleA, cycleB]), false);
});
