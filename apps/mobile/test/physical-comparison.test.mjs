import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  acceptedScanResults,
  physicalComparisonModelAsset,
} from "../src/physical-comparison.ts";

const sheet = readFileSync(new URL("../src/PhysicalComparisonSheet.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("F-043 mobile flow uses accepted scan versions and the typed metric job", () => {
  assert.match(sheet, /listScans\(workspaceId, 200\)/);
  assert.match(sheet, /acceptedScanResults\(scanSessions\)/);
  assert.match(sheet, /acceptedByVersion\.has\(version\.id\)/);
  assert.match(sheet, /comparePhysicalScan/);
  assert.match(sheet, /scale_locked/);
  assert.match(sheet, /не масштабирует сетку/);
  assert.match(sheet, /Принятый метрический скан/);
  assert.match(sheet, /Цифровая CAD-модель/);
  assert.match(sheet, /цветовой карты и оценки поверхности здесь нет/);
  assert.match(sheet, /<ModelViewer/);
  assert.match(project, /Сравнить с напечатанной деталью/);
  assert.match(project, /<PhysicalComparisonSheet/);
  assert.match(project, /designModelUrl=\{modelUrl\}/);
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
