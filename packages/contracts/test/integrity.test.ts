import assert from "node:assert/strict";
import { test } from "node:test";

import { parseIntegrityReport } from "../src/integrity.ts";

const geometry = {
  format: "glb",
  bbox_size_mm: [1200, 800, 640],
  faces: 120,
  vertices: 80,
  watertight: true,
  volume_mm3: 320_000,
  surface_area_mm2: 42_000,
  material_count: 3,
  texture_count: 2,
  node_count: 4,
  mesh_count: 2,
  animation_count: 1,
  camera_count: 1,
  light_count: 2,
};

const report = {
  schema_version: 1,
  source_format: "glb",
  target_format: "glb",
  printable_gate: false,
  status: "pass",
  checks: [
    {
      id: "texture_count",
      status: "pass",
      message: "The texture count is preserved.",
      expected: 2,
      actual: 2,
      tolerance: null,
    },
  ],
  summary: "GLB → GLB: geometry preserved.",
  source: geometry,
  output: geometry,
};

test("integrity report keeps geometry, material and texture evidence", () => {
  assert.deepEqual(parseIntegrityReport(report), {
    schemaVersion: 1,
    sourceFormat: "glb",
    targetFormat: "glb",
    printableGate: false,
    status: "pass",
    checks: [
      {
        id: "texture_count",
        status: "pass",
        message: "The texture count is preserved.",
        expected: 2,
        actual: 2,
        tolerance: null,
      },
    ],
    summary: "GLB → GLB: geometry preserved.",
    source: {
      format: "glb",
      bboxSizeMm: [1200, 800, 640],
      faces: 120,
      vertices: 80,
      watertight: true,
      volumeMm3: 320_000,
      surfaceAreaMm2: 42_000,
      materialCount: 3,
      textureCount: 2,
      nodeCount: 4,
      meshCount: 2,
      animationCount: 1,
      cameraCount: 1,
      lightCount: 2,
    },
    output: {
      format: "glb",
      bboxSizeMm: [1200, 800, 640],
      faces: 120,
      vertices: 80,
      watertight: true,
      volumeMm3: 320_000,
      surfaceAreaMm2: 42_000,
      materialCount: 3,
      textureCount: 2,
      nodeCount: 4,
      meshCount: 2,
      animationCount: 1,
      cameraCount: 1,
      lightCount: 2,
    },
  });
});

test("integrity report parser fails closed on invalid status and counts", () => {
  assert.equal(parseIntegrityReport({ ...report, status: "ready" }), null);
  assert.equal(
    parseIntegrityReport({ ...report, output: { ...geometry, texture_count: -1 } }),
    null,
  );
  assert.equal(parseIntegrityReport({ ...report, checks: [{ id: "bbox_size" }] }), null);
});

test("legacy mesh-only reports remain readable without texture counters", () => {
  const mesh = { ...geometry, material_count: null };
  delete (mesh as { texture_count?: number }).texture_count;
  const parsed = parseIntegrityReport({ ...report, source: mesh, output: mesh, checks: [] });
  assert.equal(parsed?.output.materialCount, null);
  assert.equal(parsed?.output.textureCount, null);
});
