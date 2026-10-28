import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  acceptedScanResults,
  physicalComparisonModelAsset,
  verifiedPhysicalComparison,
} from "../src/physical-comparison.ts";

const sheet = readFileSync(new URL("../src/PhysicalComparisonSheet.tsx", import.meta.url), "utf8");
const comparison = readFileSync(new URL("../src/physical-comparison.ts", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("F-043 mobile flow uses accepted scan versions and the typed metric job", () => {
  assert.match(sheet, /listScans\(workspaceId, 200\)/);
  assert.match(sheet, /acceptedScanResults\(scanSessions\)/);
  assert.match(sheet, /acceptedByVersion\.has\(version\.id\)/);
  assert.match(sheet, /comparePhysicalScan/);
  assert.match(comparison, /report\.scale_locked !== true/);
  assert.match(sheet, /verifiedPhysicalComparison\(job, versionId, selectedId, 0\.2, 3000\)/);
  assert.match(sheet, /не масштабирует сетку/);
  assert.match(sheet, /Принятый метрический скан/);
  assert.match(sheet, /Цифровая CAD-модель/);
  assert.match(sheet, /цветовой карты и оценки поверхности здесь нет/);
  assert.match(sheet, /<ModelViewer/);
  assert.match(project, /Сравнить с напечатанной деталью/);
  assert.match(project, /<PhysicalComparisonSheet/);
  assert.match(project, /designModelUrl=\{modelUrl\}/);
});

const report = {
  ok: true,
  scale_locked: true,
  registration_transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  registration_rms_mm: 0.05,
  tolerance_mm: 0.2,
  mean_mm: 0.08,
  p95_mm: 0.16,
  max_mm: 0.3,
  within_tolerance: 0.96,
  samples: 3000,
  design_size_mm: [40, 20, 10],
  scan_size_mm: [39.8, 19.9, 10.1],
  size_error_mm: [-0.2, -0.1, 0.1],
};

const job = (overrides = {}) => ({
  status: "succeeded",
  type: "physical_compare",
  project_version_id: "design-96",
  result: {
    design_version_id: "design-96",
    scan_version_id: "scan-96",
    scan_session_id: "session-96",
    report,
  },
  ...overrides,
});

test("reference 96 accepts only the exact measured comparison envelope", () => {
  assert.equal(verifiedPhysicalComparison(job(), "design-96", "scan-96", 0.2, 3000), report);
  assert.equal(verifiedPhysicalComparison(job(), "other-design", "scan-96", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job({ result: { ...job().result, scan_version_id: "other-scan" } }), "design-96", "scan-96", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job({ result: { ...job().result, report: { ...report, samples: 100 } } }), "design-96", "scan-96", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job({ result: { ...job().result, report: { ...report, within_tolerance: 1.1 } } }), "design-96", "scan-96", 0.2, 3000), null);
  assert.equal(verifiedPhysicalComparison(job({ result: { ...job().result, report: { ...report, size_error_mm: [0, 0, 0] } } }), "design-96", "scan-96", 0.2, 3000), null);
});

test("physical comparison candidates require the exact accepted scan result version", () => {
  const accepted = acceptedScanResults([
    { id: "scan-a", status: "accepted", result_version_id: "version-a" },
    { id: "scan-b", status: "ready", result_version_id: "version-b" },
    { id: "scan-c", status: "accepted", result_version_id: null },
  ]);

  assert.deepEqual([...accepted.keys()], ["version-a"]);
  assert.equal(accepted.get("version-a")?.id, "scan-a");
});

test("physical comparison previews prefer a real GLB preview and fail closed without geometry", () => {
  assert.deepEqual(physicalComparisonModelAsset({
    assets: [
      { asset_id: "mesh", role: "model", thumbnail_angle: null },
      { asset_id: "painted", role: "preview", thumbnail_angle: null },
    ],
  }), { assetId: "painted", format: "glb" });
  assert.deepEqual(physicalComparisonModelAsset({
    assets: [{ asset_id: "scan-mesh", role: "scan", thumbnail_angle: null }],
  }), { assetId: "scan-mesh", format: "stl" });
  assert.equal(physicalComparisonModelAsset({ assets: [] }), null);
});
