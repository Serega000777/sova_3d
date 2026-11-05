import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  verifiedExchangeConversion,
  verifiedExchangeDownload,
} from "../src/lib/format-conversion.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

function report(overrides: Record<string, unknown> = {}) {
  const geometry = {
    format: "obj",
    bbox_size_mm: [10, 20, 30],
    faces: 12,
    vertices: 8,
    watertight: true,
    volume_mm3: 6000,
    surface_area_mm2: 2200,
    material_count: 0,
    texture_count: 0,
    node_count: 1,
    mesh_count: 1,
    animation_count: 0,
    camera_count: 0,
    light_count: 0,
  };
  return {
    schema_version: 1,
    source_format: "stl",
    target_format: "obj",
    printable_gate: false,
    status: "pass",
    checks: [],
    summary: "verified",
    source: { ...geometry, format: "stl" },
    output: geometry,
    ...overrides,
  };
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    type: "export",
    status: "succeeded",
    project_version_id: "version-89",
    result: {
      asset_id: "asset-89",
      format: "obj",
      byte_size: 4096,
      printable_gate: false,
      report: report(),
    },
    ...overrides,
  };
}

test("reference 89 exposes every mobile mesh conversion format in the web picker", () => {
  for (const [id, title] of [
    ["obj", "OBJ"],
    ["ply", "PLY"],
    ["dae", "DAE"],
    ["x3d", "X3D"],
    ["wrl", "VRML97"],
  ]) {
    assert.match(studio, new RegExp(`id: "${id}"[\\s\\S]*?title: "${title}"`));
  }
  assert.match(studio, /WEB_EXPORTABLE_FORMATS\.map\(\(info\) =>/);
  assert.match(studio, /exportModel\(format: [^\n]+"obj"[^\n]+"wrl"/);
  assert.match(studio, /client\.exportModel\(versionId, \{ format, printable, game \}\)/);
});

test("reference 89 labels unit declaration limits and standard conventions honestly", () => {
  assert.match(studio, /OBJ cannot declare units in the file\./);
  assert.match(studio, /PLY cannot declare units in the file\./);
  assert.match(studio, /DAE\/COLLADA declares units explicitly\./);
  assert.match(studio, /Open Web3D XML: metres and \+Y up are defined by the standard\./);
  assert.match(studio, /Classic Web3D exchange in metres with \+Y up\./);
  assert.match(studio, /data-unit-declaration=\{info\.id\}/);
});

test("reference 89 loads verified STL and GLB in the real viewer before handoff", () => {
  const comparison = studio.slice(
    studio.indexOf('data-testid="verified-exchange-comparison"'),
    studio.indexOf('<div className="export-formats"'),
  );
  assert.match(studio, /format === "stl" \|\| format === "glb"/);
  assert.match(comparison, /<ModelViewer/);
  assert.match(comparison, /url=\{currentExchangePreview\.download\.url\}/);
  assert.match(comparison, /format=\{currentExchangePreview\.download\.format\}/);
  assert.match(comparison, /The immutable source remains in the main viewport/);
  assert.match(comparison, /openExchangeConversion\(currentExchangePreview\)/);
  assert.match(studio, /verifiedExchangeDownload\([\s\S]*?await client\.download\(preview\.download\.assetId\)/);
});

test("conversion results are bound to the requested immutable version format and bytes", () => {
  const verified = verifiedExchangeConversion(job() as never, "version-89", "obj", false);
  assert.equal(verified?.assetId, "asset-89");
  assert.equal(verified?.byteSize, 4096);
  assert.equal(verifiedExchangeConversion(job() as never, "other-version", "obj", false), null);
  assert.equal(
    verifiedExchangeConversion(job({ result: { ...(job().result as object), format: "ply" } }) as never, "version-89", "obj", false),
    null,
  );
  assert.equal(
    verifiedExchangeConversion(job({ result: { ...(job().result as object), report: report({ status: "fail" }) } }) as never, "version-89", "obj", false),
    null,
  );
});

test("signed handoff rejects substituted assets bytes formats and unsafe URLs", () => {
  const verified = verifiedExchangeConversion(job() as never, "version-89", "obj", false);
  assert.ok(verified);
  const download = {
    asset_id: "asset-89",
    format: "obj",
    byte_size: 4096,
    url: "https://objects.example.test/asset-89?signature=redacted",
  };
  assert.equal(verifiedExchangeDownload(verified, download as never)?.url, download.url);
  assert.equal(verifiedExchangeDownload(verified, { ...download, asset_id: "substituted" } as never), null);
  assert.equal(verifiedExchangeDownload(verified, { ...download, format: "ply" } as never), null);
  assert.equal(verifiedExchangeDownload(verified, { ...download, byte_size: 4095 } as never), null);
  assert.equal(verifiedExchangeDownload(verified, { ...download, url: "javascript:alert(1)" } as never), null);
  assert.match(studio, /activeVersionIdRef\.current !== versionId/);
  assert.match(studio, /exchangeExportRevision\.current !== requestRevision/);
});
