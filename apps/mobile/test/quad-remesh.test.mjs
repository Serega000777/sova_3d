import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseQuadTargetFaces, verifiedQuadRemeshJob } from "../src/quad-remesh.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/GameReadySheet.tsx", import.meta.url), "utf8");
const versionId = "11111111-1111-4111-8111-111111111111";
const assetId = "22222222-2222-4222-8222-222222222222";

function succeededJob(overrides = {}) {
  const report = {
    schema_version: 2,
    operation: "quad_remesh",
    blender_version: "4.3.2",
    target_faces: 4000,
    faces: 4000,
    quad_faces: 3800,
    triangle_faces: 200,
    other_faces: 0,
    vertices: 4200,
    quad_ratio: 0.95,
    source_uv_layers: 1,
    uv_layers: 1,
    uv_coordinates: 16000,
    uv_bounds: [0, 0, 1, 1],
    uv_transfer: "active_surface_projected",
    source_sha256: "a".repeat(64),
    script_sha256: "b".repeat(64),
    sandbox_network_interfaces: ["lo"],
    sandbox_uid: 65534,
    capability_effective: "0000000000000000",
    capability_permitted: "0000000000000000",
    capability_ambient: "0000000000000000",
    no_new_privileges: true,
    ...overrides.report,
  };
  return {
    id: "33333333-3333-4333-8333-333333333333",
    workspace_id: "44444444-4444-4444-8444-444444444444",
    project_id: "55555555-5555-4555-8555-555555555555",
    project_version_id: versionId,
    type: "quad_remesh",
    status: "succeeded",
    progress: 100,
    stage: null,
    result: {
      asset_id: assetId,
      format: "fbx",
      byte_size: 8192,
      source_version_id: versionId,
      target_faces: 4000,
      report,
      ...overrides.result,
    },
    error: null,
    failure_class: null,
    attempts: 1,
    cancel_requested: false,
    pause_requested: false,
    checkpoint_stage: null,
    timeout_seconds: 900,
    cost_usd: "0",
    created_at: "2026-11-01T00:00:00Z",
    started_at: "2026-11-01T00:00:01Z",
    finished_at: "2026-11-01T00:01:00Z",
    ...overrides.job,
  };
}

test("quad target parser accepts only the API's bounded integer", () => {
  assert.deepEqual(parseQuadTargetFaces("4000"), { ok: true, value: 4000 });
  assert.deepEqual(parseQuadTargetFaces(" 100000 "), { ok: true, value: 100000 });
  assert.deepEqual(parseQuadTargetFaces("99"), { ok: false });
  assert.deepEqual(parseQuadTargetFaces("100001"), { ok: false });
  assert.deepEqual(parseQuadTargetFaces("4000.5"), { ok: false });
  assert.deepEqual(parseQuadTargetFaces("4e3"), { ok: false });
});

test("mobile accepts only the exact version-bound FBX and sandbox report", () => {
  const verified = verifiedQuadRemeshJob(succeededJob(), versionId, 4000);
  assert.ok(verified);
  assert.equal(verified.assetId, assetId);
  assert.equal(verified.report.quadRatio, 0.95);
  assert.equal(verified.report.faces, 4000);
  assert.equal(verified.report.uvTransfer, "active_surface_projected");

  const legacy = succeededJob();
  legacy.result.report.schema_version = 1;
  delete legacy.result.report.source_uv_layers;
  delete legacy.result.report.uv_layers;
  delete legacy.result.report.uv_coordinates;
  delete legacy.result.report.uv_bounds;
  delete legacy.result.report.uv_transfer;
  assert.equal(verifiedQuadRemeshJob(legacy, versionId, 4000)?.report.uvTransfer, null);

  assert.equal(verifiedQuadRemeshJob(succeededJob({ job: { project_version_id: "other" } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ result: { format: "glb" } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { target_faces: 8000 } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { quad_faces: 3799 } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { capability_effective: "0000000000000001" } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { sandbox_network_interfaces: [] } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { uv_layers: 0 } }), versionId, 4000), null);
  assert.equal(verifiedQuadRemeshJob(succeededJob({ report: { uv_bounds: [1, 0, 0, 1] } }), versionId, 4000), null);
});

test("mobile verifies a schema v3 single-object report and leaves multi-object unverified", () => {
  const v3Object = {
    name: "Part",
    faces: 4000,
    quad_faces: 3800,
    triangle_faces: 200,
    other_faces: 0,
    vertices: 4200,
    quad_ratio: 0.95,
    source_uv_layers: 1,
    uv_layers: 1,
    uv_coordinates: 16000,
    uv_bounds: [0, 0, 1, 1],
    uv_transfer: "active_surface_projected",
  };
  const v3Single = succeededJob({
    report: { schema_version: 3, objects: 1, per_object: [v3Object] },
  });
  delete v3Single.result.report.source_uv_layers;
  delete v3Single.result.report.uv_layers;
  delete v3Single.result.report.uv_coordinates;
  delete v3Single.result.report.uv_bounds;
  delete v3Single.result.report.uv_transfer;
  const verifiedV3 = verifiedQuadRemeshJob(v3Single, versionId, 4000);
  assert.ok(verifiedV3);
  assert.equal(verifiedV3.report.faces, 4000);
  assert.equal(verifiedV3.report.uvTransfer, "active_surface_projected");

  const v3Multi = succeededJob({
    report: {
      schema_version: 3,
      objects: 2,
      per_object: [v3Object, { ...v3Object, name: "Copy" }],
      faces: 8000,
      quad_faces: 7600,
      triangle_faces: 400,
      vertices: 8400,
    },
  });
  delete v3Multi.result.report.source_uv_layers;
  delete v3Multi.result.report.uv_layers;
  delete v3Multi.result.report.uv_coordinates;
  delete v3Multi.result.report.uv_bounds;
  delete v3Multi.result.report.uv_transfer;
  assert.equal(verifiedQuadRemeshJob(v3Multi, versionId, 4000), null);
});

test("mobile exposes real QuadriFlow as a separate honest FBX action", () => {
  assert.match(project, /client\.createQuadRemesh\(/);
  assert.match(project, /verifiedQuadRemeshJob\(job, versionId, targetFaces\)/);
  assert.match(project, /download\.format !== "fbx"/);
  assert.match(project, /activeIdRef\.current !== versionId/);
  assert.match(sheet, /Quad · FBX/);
  assert.match(sheet, /onRunQuad\(parsedQuadTarget\.value\)/);
  assert.match(sheet, /проецирует активную UV-карту/);
  assert.match(sheet, /Швы не перестраиваются, покраска не перепекается/);
  assert.match(sheet, /не обещание точного числа или 100% quad/);
  assert.match(sheet, /quadResult\.report\.quadRatio/);
  assert.match(sheet, /active map was surface-projected/);
  assert.match(sheet, /Linking\.openURL\(quadResult\.downloadUrl\)/);
  assert.doesNotMatch(sheet, /Quad · \{ru \? "скоро" : "soon"\}/);
});
