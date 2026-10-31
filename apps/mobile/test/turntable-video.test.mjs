import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  verifiedTurntableDownload,
  verifiedTurntableVideoJob,
} from "../src/turntable-video.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const nativeFile = readFileSync(new URL("../src/turntable-video-file.ts", import.meta.url), "utf8");

const versionId = "11111111-1111-4111-8111-111111111111";
const sourceAssetId = "22222222-2222-4222-8222-222222222222";
const assetId = "33333333-3333-4333-8333-333333333333";

function job(overrides = {}) {
  return {
    type: "render_turntable_video",
    status: "succeeded",
    project_version_id: versionId,
    result: {
      version_id: versionId,
      source_asset_id: sourceAssetId,
      asset_id: assetId,
      metadata: {
        width: 480,
        height: 320,
        fps: 12,
        frame_count: 12,
        duration_seconds: 1,
        render_kind: "deterministic_turntable",
      },
    },
    ...overrides,
  };
}

test("mobile accepts only the exact version-scoped deterministic video result", () => {
  const video = verifiedTurntableVideoJob(job(), versionId);
  assert.deepEqual(video, {
    versionId,
    sourceAssetId,
    assetId,
    width: 480,
    height: 320,
    fps: 12,
    frameCount: 12,
    durationSeconds: 1,
  });
  assert.equal(verifiedTurntableVideoJob(job({ status: "failed" }), versionId), null);
  assert.equal(verifiedTurntableVideoJob(job({ type: "export" }), versionId), null);
  assert.equal(verifiedTurntableVideoJob(job(), "44444444-4444-4444-8444-444444444444"), null);
  assert.equal(verifiedTurntableVideoJob(job({ result: { ...job().result, version_id: sourceAssetId } }), versionId), null);
  assert.equal(verifiedTurntableVideoJob(job({ result: { ...job().result, asset_id: "not-an-id" } }), versionId), null);
  assert.equal(verifiedTurntableVideoJob(job({ result: { ...job().result, metadata: { ...job().result.metadata, fps: 24 } } }), versionId), null);
  assert.equal(verifiedTurntableVideoJob(job({ result: { ...job().result, metadata: { ...job().result.metadata, render_kind: "ai_video" } } }), versionId), null);
});

test("mobile binds the signed download to the exact non-empty MP4 asset", () => {
  const video = verifiedTurntableVideoJob(job(), versionId);
  assert.ok(video);
  const download = {
    asset_id: assetId,
    url: "https://assets.example.test/video.mp4?signature=one",
    format: "mp4",
    byte_size: 20_129,
    expires_in_seconds: 900,
    created_at: "2026-10-31T14:30:00Z",
  };
  assert.deepEqual(verifiedTurntableDownload(video, download), {
    url: download.url,
    byteSize: 20_129,
  });
  for (const patch of [
    { asset_id: sourceAssetId },
    { format: "glb" },
    { byte_size: 0 },
    { expires_in_seconds: 0 },
    { created_at: "invalid" },
    { url: "http://assets.example.test/video.mp4" },
    { url: "file:///private/video.mp4" },
  ]) {
    assert.equal(verifiedTurntableDownload(video, { ...download, ...patch }), null);
  }
});

test("mobile export UI reaches the typed job and native MP4 handoff honestly", () => {
  assert.match(project, /client\.renderVersionTurntableVideo\(versionId\)/);
  assert.match(project, /verifiedTurntableVideoJob\(job, versionId\)/);
  assert.match(project, /activeIdRef\.current !== versionId/);
  assert.match(project, /shareTurntableVideo\(client, video\)/);
  assert.match(project, /deterministic 360° render/);
  assert.match(project, /не AI-видео/);
  assert.match(nativeFile, /File\.downloadFileAsync\(download\.url, target, \{ idempotent: true \}\)/);
  assert.match(nativeFile, /file\.size !== download\.byteSize/);
  assert.match(nativeFile, /mimeType: "video\/mp4"/);
  assert.doesNotMatch(project, /AI-дорисов|cinematic|звук/);
});
