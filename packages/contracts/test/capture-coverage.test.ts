import assert from "node:assert/strict";
import test from "node:test";

import { azimuthSectorCoverage, guidedTurntableAngle } from "../src/capture-coverage.ts";

test("guided turntable distributes frames evenly around one revolution", () => {
  assert.deepEqual(
    Array.from({ length: 8 }, (_, index) => guidedTurntableAngle(index, 8)),
    [0, 45, 90, 135, 180, 225, 270, 315],
  );
  assert.equal(guidedTurntableAngle(8, 8), 0);
});

test("guided turntable fails closed to bounded numeric defaults", () => {
  assert.equal(guidedTurntableAngle(-4, 24), 0);
  assert.equal(guidedTurntableAngle(Number.NaN, Number.NaN), 0);
  assert.equal(guidedTurntableAngle(3, 0), 0);
});

test("no frames means no sector is covered", () => {
  const coverage = azimuthSectorCoverage([], 12);
  assert.equal(coverage.coveredSectors, 0);
  assert.equal(coverage.coveragePercent, 0);
  assert.deepEqual(coverage.covered, new Array(12).fill(false));
});

test("azimuths wrap past 360 and below 0 onto the same ring", () => {
  const coverage = azimuthSectorCoverage([0, 360, -360], 12);
  assert.equal(coverage.coveredSectors, 1);
  assert.equal(coverage.covered[0], true);
});

test("a full walk-around covers every sector", () => {
  const azimuths = Array.from({ length: 24 }, (_, i) => i * 15);
  const coverage = azimuthSectorCoverage(azimuths, 12);
  assert.equal(coverage.coveredSectors, 12);
  assert.equal(coverage.coveragePercent, 100);
});

test("non-finite azimuths are ignored rather than crashing a sector index", () => {
  const coverage = azimuthSectorCoverage([NaN, Infinity, -Infinity, 45], 12);
  assert.equal(coverage.coveredSectors, 1);
});

test("sector count is bounded to at least one sector", () => {
  const coverage = azimuthSectorCoverage([10], 0);
  assert.equal(coverage.sectorCount, 1);
  assert.equal(coverage.coveredSectors, 1);
});
