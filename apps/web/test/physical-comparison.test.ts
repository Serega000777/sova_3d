import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  acceptedScanResults,
  safeModelDownload,
  verifiedPhysicalComparison,
} from "../src/lib/physical-comparison.ts";

const panel = readFileSync(new URL("../src/components/PhysicalComparisonPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const report = {
  ok: true,
  registration_transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  registration_rms_mm: 0.05,
  tolerance_mm: 0.2,
  mean_mm: 0.04,
  p95_mm: 0.1,
  max_mm: 0.18,
  within_tolerance: 0.98,
  samples: 3000,
  design_size_mm: [10, 20, 30],
  scan_size_mm: [10.1, 19.9, 30.05],
  size_error_mm: [0.1, -0.1, 0.05],
  scale_locked: true,
};

const job = (overrides: Record<string, unknown> = {}) => ({
  id: "job-58",
  type: "physical_compare",
  status: "succeeded",
  project_version_id: "design-v1",
  result: { design_version_id: "design-v1", scan_version_id: "scan-v1", scan_session_id: "scan-1", report },
  ...overrides,
}) as never;

test("reference 58 web comparison uses only accepted metric scan results", () => {
  const scans = acceptedScanResults([
    { id: "accepted", status: "accepted", mode: "scanner", capabilities: { metric_scale: "scanner" }, scale_hint_mm: null, scale_confidence: null, result_version_id: "scan-v1" },
    { id: "ready", status: "ready", mode: "scanner", capabilities: { metric_scale: "scanner" }, scale_hint_mm: null, scale_confidence: null, result_version_id: "scan-v2" },
    { id: "missing", status: "accepted", mode: "scanner", capabilities: { metric_scale: "scanner" }, scale_hint_mm: null, scale_confidence: null, result_version_id: null },
    { id: "unmeasured", status: "accepted", mode: "rgb", capabilities: { metric_scale: "none" }, scale_hint_mm: null, scale_confidence: null, result_version_id: "scan-v3" },
  ] as never);
  assert.equal(scans.get("scan-v1")?.id, "accepted");
  assert.equal(scans.has("scan-v2"), false);
  assert.equal(scans.has("scan-v3"), false);
  assert.match(panel, /client\.listScans\(workspaceId, 200\)/);
  assert.match(panel, /acceptedScanResults\(scans\)/);
});

test("metrology report is bound to exact design scan tolerance samples and locked scale", () => {
  assert.equal(verifiedPhysicalComparison(job(), "design-v1", "scan-v1", 0.2, 3000)?.within_tolerance, 0.98);
  assert.equal(verifiedPhysicalComparison(job(), "other", "scan-v1", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job(), "design-v1", "other", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job(), "design-v1", "scan-v1", 0.3, 3000), null);
  assert.equal(verifiedPhysicalComparison(job({ result: { design_version_id: "design-v1", scan_version_id: "scan-v1", scan_session_id: "scan-1", report: { ...report, scale_locked: false } } }), "design-v1", "scan-v1", 0.2, 3000), null);
});

test("scan preview accepts only the expected downloadable model asset", () => {
  const expected = { assetId: "asset-1", format: "stl" as const };
  assert.equal(safeModelDownload({ asset_id: "asset-1", format: "stl", byte_size: 12, url: "https://files.example/scan.stl" }, expected), "https://files.example/scan.stl");
  assert.equal(safeModelDownload({ asset_id: "other", format: "stl", byte_size: 12, url: "https://files.example/scan.stl" }, expected), null);
  assert.equal(safeModelDownload({ asset_id: "asset-1", format: "stl", byte_size: 12, url: "javascript:alert(1)" }, expected), null);
});

test("web UI runs exact bounded comparison and never claims heat-map or surface verdict", () => {
  assert.match(panel, /client\.comparePhysicalScan\(versionId/);
  assert.match(panel, /tolerance_mm: TOLERANCE_MM/);
  assert.match(panel, /samples: SAMPLES/);
  assert.match(panel, /verifiedPhysicalComparison\(job, versionId, selectedId, TOLERANCE_MM, SAMPLES\)/);
  assert.match(panel, /цветовой карты и оценки поверхности здесь нет/);
  assert.match(panel, /не масштабирует сетку/);
  assert.match(studio, /tool === "metrology"/);
});

test("printer calibration is a separate explicit action bound to the comparison job", () => {
  assert.match(panel, /client\.calibratePrinterFromComparison\(printerId, comparisonJobId\)/);
  assert.match(panel, /profile\.id !== printerId/);
  assert.match(panel, /Только безопасная равномерная поправка усадки X\/Y/);
  assert.match(panel, /Отверстия, поток, температура и Z не меняются/);
});
