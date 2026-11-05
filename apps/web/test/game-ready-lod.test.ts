import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  gameReadyEnvelopeMatchesRequest,
  gameReadyLodsMatchRequest,
  gameReadySceneReportMatchesRequest,
  parseLodShares,
} from "../src/lib/game-ready-lod.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../src/components/GameReadyLodCard.tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/components/ModelViewer.tsx", import.meta.url), "utf8");

test("LOD1/LOD2 shares must be 1-99% and LOD2 strictly lighter than LOD1", () => {
  assert.deepEqual(parseLodShares("50", "20"), { ok: true, ratios: [0.5, 0.2] });
  assert.deepEqual(parseLodShares("50,5", "20,1"), { ok: true, ratios: [0.505, 0.201] });
  assert.deepEqual(parseLodShares("0", "20"), { ok: false, reason: "range" });
  assert.deepEqual(parseLodShares("100", "20"), { ok: false, reason: "range" });
  assert.deepEqual(parseLodShares("abc", "20"), { ok: false, reason: "range" });
  assert.deepEqual(parseLodShares("20", "50"), { ok: false, reason: "order" });
  assert.deepEqual(parseLodShares("20", "20"), { ok: false, reason: "order" });
});

function makeLod(index: number, triangles: number): { name: string; triangles: number; vertices: number; max_deviation_mm: number } {
  return { name: `SovaModel_LOD${index}`, triangles, vertices: triangles * 2, max_deviation_mm: index === 0 ? 0 : 0.05 * index };
}

test("single-object LOD evidence must name every level in order with non-increasing triangles", () => {
  const good = [makeLod(0, 9000), makeLod(1, 4500), makeLod(2, 1800)];
  assert.equal(gameReadyLodsMatchRequest(good, "SovaModel", 10_000, 2), true);
  // LOD0 over budget fails closed.
  assert.equal(gameReadyLodsMatchRequest([makeLod(0, 20_000), makeLod(1, 4500), makeLod(2, 1800)], "SovaModel", 10_000, 2), false);
  // Triangle count increasing between levels fails closed.
  assert.equal(gameReadyLodsMatchRequest([makeLod(0, 9000), makeLod(1, 9500), makeLod(2, 1800)], "SovaModel", 10_000, 2), false);
  // Wrong level count fails closed.
  assert.equal(gameReadyLodsMatchRequest([makeLod(0, 9000), makeLod(1, 4500)], "SovaModel", 10_000, 2), false);
  // Substituted name fails closed.
  assert.equal(
    gameReadyLodsMatchRequest([{ ...good[0], name: "OtherModel_LOD0" }, good[1], good[2]], "SovaModel", 10_000, 2),
    false,
  );
});

test("single-object envelope requires the exact pivot, byte size and a LOD0 within the source triangles", () => {
  const lods = [makeLod(0, 9000), makeLod(1, 4500), makeLod(2, 1800)];
  const report = { ok: true, pivot: "base", file_bytes: 1234, triangles_in: 50_000, lods };
  assert.equal(gameReadyEnvelopeMatchesRequest(report, 1234, "base"), true);
  assert.equal(gameReadyEnvelopeMatchesRequest({ ...report, pivot: "centre" }, 1234, "base"), false);
  assert.equal(gameReadyEnvelopeMatchesRequest({ ...report, file_bytes: 999 }, 1234, "base"), false);
  assert.equal(gameReadyEnvelopeMatchesRequest({ ...report, ok: false }, 1234, "base"), false);
});

function makeObjectLod(engineName: string, index: number, triangles: number) {
  return { name: `${engineName}_LOD${index}`, triangles, vertices: triangles * 2, max_deviation_mm: index === 0 ? 0 : 0.05 * index };
}

function makeObject(nodeId: string, sourceName: string, engineName: string, trianglesIn: number) {
  return {
    node_id: nodeId,
    source_name: sourceName,
    name: engineName,
    report: {
      ok: true,
      pivot: "keep",
      triangles_in: trianglesIn,
      lods: [
        makeObjectLod(engineName, 0, Math.round(trianglesIn * 0.9)),
        makeObjectLod(engineName, 1, Math.round(trianglesIn * 0.4)),
        makeObjectLod(engineName, 2, Math.round(trianglesIn * 0.15)),
      ],
    },
  };
}

test("aggregate scene report fails closed when a per-object triangle sum does not match the reported total", () => {
  const objectA = makeObject("node-a", "Base", "Base", 10_000);
  const objectB = makeObject("node-b", "Lid", "Lid", 6_000);
  const report = {
    ok: true,
    pivot: "base",
    file_bytes: 5000,
    objects: 2,
    triangles_in: 16_000,
    per_object: [objectA, objectB],
  };
  const verified = gameReadySceneReportMatchesRequest(report, 5000, "base", 10_000, 2);
  assert.ok(verified);
  assert.equal(verified!.length, 2);
  assert.deepEqual(verified!.map((entry) => entry.nodeId), ["node-a", "node-b"]);

  // Summed source triangles disagree with the declared total: fail closed.
  const mismatched = { ...report, triangles_in: 99_999 };
  assert.equal(gameReadySceneReportMatchesRequest(mismatched, 5000, "base", 10_000, 2), null);
});

test("aggregate scene report fails closed when a visible object's evidence is missing or duplicated", () => {
  const objectA = makeObject("node-a", "Base", "Base", 10_000);
  const objectB = makeObject("node-b", "Lid", "Lid", 6_000);
  const base = {
    ok: true,
    pivot: "base",
    file_bytes: 5000,
    objects: 2,
    triangles_in: 16_000,
    per_object: [objectA, objectB],
  };

  // `objects` count claims 2 but only one entry is present: fail closed.
  const missing = { ...base, per_object: [objectA] };
  assert.equal(gameReadySceneReportMatchesRequest(missing, 5000, "base", 10_000, 2), null);

  // Duplicated node id instead of a second distinct object: fail closed.
  const duplicated = { ...base, per_object: [objectA, { ...objectA }] };
  assert.equal(gameReadySceneReportMatchesRequest(duplicated, 5000, "base", 10_000, 2), null);

  // A substituted/malformed per-object LOD set fails closed even though the envelope matches.
  const corrupted = {
    ...base,
    per_object: [objectA, { ...objectB, report: { ...objectB.report, lods: [] } }],
  };
  assert.equal(gameReadySceneReportMatchesRequest(corrupted, 5000, "base", 10_000, 2), null);
});

test("web wires the LOD card through the existing export job and fail-closed validators", () => {
  assert.match(studio, /import \{\s*gameReadyEnvelopeMatchesRequest,\s*gameReadyLodsMatchRequest,\s*gameReadySceneReportMatchesRequest,/);
  assert.match(studio, /async function runGameReadyLod/);
  assert.match(studio, /collider: "none",\s*lod_ratios: options\.lodRatios,\s*uv: false,\s*pivot: "base",/);
  assert.match(studio, /gameReadySceneReportMatchesRequest\(\s*result\.report,/);
  assert.match(studio, /gameReadyLodsMatchRequest\(reportLods, modelName, options\.maxTriangles, options\.lodRatios\.length\)/);
  assert.match(studio, /gameReadyEnvelopeMatchesRequest\(result\.report, result\.byte_size, "base"\)/);
  assert.match(studio, /<GameReadyLodCard/);
  assert.match(studio, /onRun=\{runGameReadyLod\}/);
});

test("the whole-scene preview loads every verified object's own chosen LOD node from the shared download", () => {
  assert.match(
    card,
    /result\.objects\.map\(\(entry, index\) => \(\{\s*id: entry\.nodeId,\s*url: result\.downloadUrl,\s*format: "glb" as const,\s*worldTransform: \[\],\s*glbMeshName: names\[index\]!,/,
  );
});

test("the single-object preview resolves exactly the selected object's chosen LOD node", () => {
  assert.match(card, /const name = previewObject \? previewObject\.lods\[previewLodIndex\]\?\.name : result\.lods\?\.\[previewLodIndex\]\?\.name;/);
  assert.match(card, /glbMeshName: name,/);
});

test("ModelViewer can load a named mesh from a multi-node GLB instead of always taking the first mesh", () => {
  assert.match(viewer, /glbMeshName\?: string \| null;/);
  assert.match(
    viewer,
    /const first = source\.glbMeshName != null\s*\? meshes\.find\(\(mesh\) => mesh\.name === source\.glbMeshName\)\s*: meshes\[0\];/,
  );
});
