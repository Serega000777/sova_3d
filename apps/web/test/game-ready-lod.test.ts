import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  gameReadyEnvelopeMatchesRequest,
  gameReadyLodsMatchRequest,
  gameReadySceneReportMatchesRequest,
  gameReadyUvAtlasesMatchLods,
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

function makeUvAtlas(lod: { name: string }, triangleAreaPct: number) {
  return { lod: lod.name, triangle_area_pct: triangleAreaPct, degenerate_triangles: 0, out_of_bounds_vertices: 0 };
}

test("UV atlas evidence must cover every verified LOD by name, with finite positive area and non-negative counts", () => {
  const lods = [makeLod(0, 9000), makeLod(1, 4500), makeLod(2, 1800)];
  const atlases = lods.map((lod) => makeUvAtlas(lod, 62.5));
  assert.deepEqual(
    gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: atlases }, lods, true),
    lods.map((lod) => ({ lod: lod.name, triangleAreaPct: 62.5, degenerateTriangles: 0, outOfBoundsVertices: 0 })),
  );
  // UV not requested: the report must agree, and an empty (not fabricated) evidence list is valid.
  assert.deepEqual(gameReadyUvAtlasesMatchLods({ uv: false, uv_atlases: [] }, lods, false), []);
  // Claims UV but the request didn't ask for it (or vice versa): fail closed.
  assert.equal(gameReadyUvAtlasesMatchLods({ uv: false, uv_atlases: atlases }, lods, true), null);
  assert.equal(gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: atlases }, lods, false), null);
  // Wrong atlas count fails closed.
  assert.equal(gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: atlases.slice(0, 1) }, lods, true), null);
  // Substituted LOD name fails closed.
  assert.equal(
    gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: [{ ...atlases[0], lod: "Other_LOD0" }, atlases[1], atlases[2]] }, lods, true),
    null,
  );
  // Non-finite or non-positive area fails closed.
  assert.equal(
    gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: [{ ...atlases[0], triangle_area_pct: Number.NaN }, atlases[1], atlases[2]] }, lods, true),
    null,
  );
  assert.equal(
    gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: [{ ...atlases[0], triangle_area_pct: 0 }, atlases[1], atlases[2]] }, lods, true),
    null,
  );
  // Negative degenerate/out-of-bounds counts fail closed.
  assert.equal(
    gameReadyUvAtlasesMatchLods({ uv: true, uv_atlases: [{ ...atlases[0], degenerate_triangles: -1 }, atlases[1], atlases[2]] }, lods, true),
    null,
  );
});

function makeObjectLod(engineName: string, index: number, triangles: number) {
  return { name: `${engineName}_LOD${index}`, triangles, vertices: triangles * 2, max_deviation_mm: index === 0 ? 0 : 0.05 * index };
}

function makeObject(nodeId: string, sourceName: string, engineName: string, trianglesIn: number) {
  const lods = [
    makeObjectLod(engineName, 0, Math.round(trianglesIn * 0.9)),
    makeObjectLod(engineName, 1, Math.round(trianglesIn * 0.4)),
    makeObjectLod(engineName, 2, Math.round(trianglesIn * 0.15)),
  ];
  return {
    node_id: nodeId,
    source_name: sourceName,
    name: engineName,
    report: {
      ok: true,
      pivot: "keep",
      triangles_in: trianglesIn,
      lods,
      uv: true,
      uv_atlases: lods.map((lod) => makeUvAtlas(lod, 55)),
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
  const verified = gameReadySceneReportMatchesRequest(report, 5000, "base", 10_000, 2, true);
  assert.ok(verified);
  assert.equal(verified!.length, 2);
  assert.deepEqual(verified!.map((entry) => entry.nodeId), ["node-a", "node-b"]);
  assert.equal(verified![0]!.uvAtlases.length, 3);
  assert.equal(verified![0]!.uvAtlases[0]!.triangleAreaPct, 55);

  // Summed source triangles disagree with the declared total: fail closed.
  const mismatched = { ...report, triangles_in: 99_999 };
  assert.equal(gameReadySceneReportMatchesRequest(mismatched, 5000, "base", 10_000, 2, true), null);
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
  assert.equal(gameReadySceneReportMatchesRequest(missing, 5000, "base", 10_000, 2, true), null);

  // Duplicated node id instead of a second distinct object: fail closed.
  const duplicated = { ...base, per_object: [objectA, { ...objectA }] };
  assert.equal(gameReadySceneReportMatchesRequest(duplicated, 5000, "base", 10_000, 2, true), null);

  // A substituted/malformed per-object LOD set fails closed even though the envelope matches.
  const corrupted = {
    ...base,
    per_object: [objectA, { ...objectB, report: { ...objectB.report, lods: [] } }],
  };
  assert.equal(gameReadySceneReportMatchesRequest(corrupted, 5000, "base", 10_000, 2, true), null);
});

test("aggregate scene report fails closed when a visible object's UV evidence is absent or substituted", () => {
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
  assert.ok(gameReadySceneReportMatchesRequest(base, 5000, "base", 10_000, 2, true));

  // One object's UV atlas list is dropped entirely: fail closed.
  const droppedUv = {
    ...base,
    per_object: [objectA, { ...objectB, report: { ...objectB.report, uv_atlases: [] } }],
  };
  assert.equal(gameReadySceneReportMatchesRequest(droppedUv, 5000, "base", 10_000, 2, true), null);

  // One object's UV atlas is substituted with another object's LOD name: fail closed.
  const substitutedUv = {
    ...base,
    per_object: [
      objectA,
      {
        ...objectB,
        report: {
          ...objectB.report,
          uv_atlases: [{ ...objectB.report.uv_atlases[0], lod: "Base_LOD0" }, objectB.report.uv_atlases[1], objectB.report.uv_atlases[2]],
        },
      },
    ],
  };
  assert.equal(gameReadySceneReportMatchesRequest(substitutedUv, 5000, "base", 10_000, 2, true), null);

  // An object claims UV false while the scene requested UV true: fail closed.
  const uvNotRequested = {
    ...base,
    per_object: [objectA, { ...objectB, report: { ...objectB.report, uv: false } }],
  };
  assert.equal(gameReadySceneReportMatchesRequest(uvNotRequested, 5000, "base", 10_000, 2, true), null);
});

test("web wires the LOD card through the existing export job and fail-closed validators", () => {
  assert.match(studio, /import \{\s*gameReadyEnvelopeMatchesRequest,\s*gameReadyLodsMatchRequest,\s*gameReadySceneReportMatchesRequest,\s*gameReadyUvAtlasesMatchLods,/);
  assert.match(studio, /async function runGameReadyLod/);
  assert.match(studio, /collider: "none",\s*lod_ratios: options\.lodRatios,\s*uv: true,\s*pivot: "base",/);
  assert.match(studio, /gameReadySceneReportMatchesRequest\(\s*result\.report,/);
  assert.match(studio, /gameReadyLodsMatchRequest\(reportLods, modelName, options\.maxTriangles, options\.lodRatios\.length\)/);
  assert.match(studio, /gameReadyEnvelopeMatchesRequest\(result\.report, result\.byte_size, "base"\)/);
  assert.match(studio, /gameReadyUvAtlasesMatchLods\(result\.report, lods, true\)/);
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

test("the checker-preview toggle only appears with UV evidence, and swaps the viewer's material without changing which node is requested", () => {
  assert.match(card, /const debugAppearance = previewAppearance === "uv_checker" \? "uv_checker" as const : null;/);
  assert.match(card, /previewUvAtlases\.length > 0 \?/);
  assert.match(card, /setPreviewAppearance\("source"\)/);
  // The toggle feeds ModelViewer's standalone `debugAppearance` prop; it never appears inside
  // the `previewSceneParts` builder, so it cannot change which `glbMeshName` is resolved.
  assert.doesNotMatch(card, /glbMeshName: names\[index\]!,\s*debugAppearance,/);
  assert.doesNotMatch(card, /glbMeshName: name,\s*debugAppearance,/);
  assert.match(card, /debugAppearance=\{debugAppearance\}/);
});

test("ModelViewer can load a named mesh from a multi-node GLB instead of always taking the first mesh", () => {
  assert.match(viewer, /glbMeshName\?: string \| null;/);
  assert.match(
    viewer,
    /const first = source\.glbMeshName != null\s*\? meshes\.find\(\(mesh\) => mesh\.name === source\.glbMeshName\)\s*: meshes\[0\];/,
  );
});

test("ModelViewer renders a UV-space checker override as a render-time material swap, without touching geometry loading or the normal textured material", () => {
  assert.match(viewer, /debugAppearance\?: "uv_checker" \| null;/);
  assert.match(viewer, /debugAppearance = null,/);
  assert.match(viewer, /debugAppearance === "uv_checker"/);
  assert.match(viewer, /vUv = uv;/);
  assert.match(viewer, /floor\(vUv \* 16\.0\)/);
  // The checker branch and the normal material branch are mutually exclusive.
  assert.match(viewer, /<shaderMaterial[\s\S]*?\/>\s*\) : \(\s*<meshStandardMaterial/);
  // The override is a top-level ModelViewer/Body render prop, not a field on ViewerScenePart
  // or ViewerBody — so toggling it cannot force the GLB to be re-fetched or re-parsed.
  const scenePartInterface = viewer.slice(viewer.indexOf("export interface ViewerScenePart"), viewer.indexOf("export interface ComponentSelectionInfo"));
  assert.doesNotMatch(scenePartInterface, /debugAppearance/);
  const viewerBodyInterface = viewer.slice(viewer.indexOf("export interface ViewerBody"), viewer.indexOf("export interface ViewerAppearance"));
  assert.doesNotMatch(viewerBodyInterface, /debugAppearance/);
});
