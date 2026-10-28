import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { verifiedExchangeConversion } from "../src/format-conversion.ts";

const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 89 exposes the server-supported exchange conversion paths", () => {
  assert.match(source, /format: "stl" \| "3mf" \| "glb" \| "obj" \| "ply" \| "dae" \| "fbx" \| "usdz" \| "x3d" \| "wrl"/);
  assert.match(source, /format: "obj", title: "OBJ"/);
  assert.match(source, /format: "ply", title: "PLY"/);
  assert.match(source, /format: "dae", title: "DAE"/);
  assert.match(source, /format: "fbx", title: "FBX"/);
  assert.match(source, /format: "x3d", title: "X3D"/);
  assert.match(source, /format: "wrl", title: "VRML97"/);
  assert.match(source, /client\.exportModel\(active\.id, \{/);
  assert.match(source, /const download = await client\.download\(result\.asset_id\)/);
});

test("reference 52 hands a real USDZ export to the system AR viewer", () => {
  assert.match(source, /format: "usdz", title: "USDZ"/);
  assert.match(source, /AR Quick Look на совместимом iPhone\/iPad/);
  assert.match(source, /client\.download\(result\.asset_id\)/);
  assert.match(source, /await Linking\.openURL\(download\.url\)/);
  assert.match(source, /без выдуманного масштаба или привязки/);
});

test("mobile conversion copy does not invent unit or axis controls", () => {
  assert.match(source, /Геометрия хранится[\s\S]*в миллиметрах/);
  assert.match(source, /ручная смена масштаба и осей при экспорте пока недоступна/);
  assert.doesNotMatch(source, /target units|up-axis|Ось Y вверх/);
});

function report(overrides = {}) {
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

function job(overrides = {}) {
  return {
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

test("reference 89 downloads only an exact version-bound conversion report", () => {
  const verified = verifiedExchangeConversion(job(), "version-89", "obj", false);
  assert.equal(verified?.assetId, "asset-89");
  assert.equal(verified?.byteSize, 4096);
  assert.equal(verified?.report.targetFormat, "obj");
  assert.equal(verifiedExchangeConversion(job(), "other-version", "obj", false), null);
  assert.equal(verifiedExchangeConversion(job({ result: { ...job().result, format: "ply" } }), "version-89", "obj", false), null);
  assert.equal(verifiedExchangeConversion(job({ result: { ...job().result, byte_size: 0 } }), "version-89", "obj", false), null);
  assert.equal(verifiedExchangeConversion(job({ result: { ...job().result, report: report({ target_format: "ply" }) } }), "version-89", "obj", false), null);
  assert.equal(verifiedExchangeConversion(job({ result: { ...job().result, report: report({ status: "fail" }) } }), "version-89", "obj", false), null);
  assert.match(source, /verifiedExchangeConversion\(/);
  assert.match(source, /проверен сервером/);
});
