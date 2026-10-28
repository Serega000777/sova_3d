import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  gameReadyLodsMatchRequest,
  gameReadyUvReportMatchesLods,
  parseLodRatios,
} from "../src/game-ready.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/GameReadySheet.tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");

test("mobile game-ready export reaches the typed GLB pipeline with real controls", () => {
  assert.match(project, /client\.exportModel\(active\.id, \{[\s\S]*format: "glb",[\s\S]*game: \{/);
  assert.match(project, /max_triangles: options\.maxTriangles/);
  assert.match(project, /collider: options\.collider/);
  assert.match(project, /lod_ratios: options\.lodRatios/);
  assert.match(project, /uv: options\.uv/);
  assert.match(project, /if \(job\.status !== "succeeded"\)/);
  assert.match(project, /client\.download\(result\.asset_id\)/);
});

test("game-ready sheet reuses shared budgets and states the topology boundary honestly", () => {
  assert.match(sheet, /GAME_BUDGETS\.map/);
  assert.match(sheet, /parseLodRatios\(lod1Percent, lod2Percent\)/);
  assert.match(sheet, /lods && parsedLods\.ok \? parsedLods\.ratios : \[\]/);
  assert.match(sheet, /Quad · \{ru \? "скоро" : "soon"\}/);
  assert.match(sheet, /проверяемая треугольная decimation/);
  assert.match(sheet, /Linking\.openURL\(result\.downloadUrl\)/);
});

test("custom LOD percentages become descending worker ratios", () => {
  assert.deepEqual(parseLodRatios("65", "25"), { ok: true, ratios: [0.65, 0.25] });
  assert.deepEqual(parseLodRatios("50,5", "12,5"), { ok: true, ratios: [0.505, 0.125] });
  assert.deepEqual(parseLodRatios("20", "50"), { ok: false, reason: "order" });
  assert.deepEqual(parseLodRatios("100", "20"), { ok: false, reason: "range" });
  assert.deepEqual(parseLodRatios("", "20"), { ok: false, reason: "range" });
});

test("game-ready result exposes only the verified contents reported by the worker", () => {
  assert.match(sheet, /Проверенный состав игрового GLB/);
  assert.match(sheet, /result\.report\.lods\?\.length/);
  assert.match(sheet, /Проверенные уровни детализации/);
  assert.match(sheet, /lod\.triangles\.toLocaleString/);
  assert.match(sheet, /lod\.max_deviation_mm\.toLocaleString/);
  assert.match(sheet, /отклонение ≤/);
  assert.match(sheet, /result\.report\.uv/);
  assert.match(sheet, /result\.report\.uv_atlases\?\.map/);
  assert.match(sheet, /atlas\.triangle_area_pct\.toLocaleString/);
  assert.match(sheet, /atlas\.out_of_bounds_vertices/);
  assert.match(sheet, /atlas\.degenerate_triangles/);
  assert.match(sheet, /result\.report\.baked_texture_px/);
  assert.match(sheet, /result\.report\.collider\.triangles/);
  assert.match(sheet, /result\.report\.collider\.triangle_limit/);
  assert.match(sheet, /result\.report\.collider\.is_convex/);
  assert.match(sheet, /result\.report\.collider\.is_watertight/);
  assert.match(sheet, /result\.report\.collider\.volume_ratio_pct/);
  assert.match(sheet, /result\.report\.collider\.floor_offset_mm/);
  assert.match(sheet, /Столкновения между объектами сцены, массу, гравитацию и динамику он не моделирует/);
  assert.doesNotMatch(sheet, /UnityPackage|\.uproject|готовый пакет для Unity|готовый пакет для Unreal/);
});

test("reference 83 previews exactly one verified GLB LOD node at a time", () => {
  assert.match(sheet, /setPreviewLod\(result\?\.report\?\.lods\?\.\[0\]\?\.name \?\? null\)/);
  assert.match(sheet, /glbMeshName=\{previewLod\}/);
  assert.match(sheet, /result\.report\.lods\.map/);
  assert.match(sheet, /ручное сравнение, не автоматический выбор по расстоянию/);
  assert.match(viewer, /child\.name === meshName/);
  assert.match(viewer, /the file has no mesh named/);
});

test("reference 83 accepts only the exact ordered and measured LOD report", () => {
  const lods = [
    { name: "SovaModel_LOD0", triangles: 20_000, vertices: 10_002, max_deviation_mm: 0 },
    { name: "SovaModel_LOD1", triangles: 10_000, vertices: 5_002, max_deviation_mm: 0.2 },
    { name: "SovaModel_LOD2", triangles: 4_000, vertices: 2_002, max_deviation_mm: 0.5 },
  ];
  assert.equal(gameReadyLodsMatchRequest(lods, "SovaModel", 20_000, 2), true);
  assert.equal(gameReadyLodsMatchRequest(lods.slice(0, 2), "SovaModel", 20_000, 2), false);
  assert.equal(gameReadyLodsMatchRequest(lods.map((lod, index) => index === 1 ? { ...lod, name: "Other_LOD1" } : lod), "SovaModel", 20_000, 2), false);
  assert.equal(gameReadyLodsMatchRequest(lods.map((lod, index) => index === 2 ? { ...lod, triangles: 11_000 } : lod), "SovaModel", 20_000, 2), false);
  assert.equal(gameReadyLodsMatchRequest(lods.map((lod, index) => index === 2 ? { ...lod, max_deviation_mm: Number.NaN } : lod), "SovaModel", 20_000, 2), false);
  assert.match(project, /gameReadyLodsMatchRequest\(/);
  assert.match(project, /options\.lodRatios\.length/);
});

test("reference 84 inspects the exported UV coordinates with an honest checker", () => {
  assert.match(sheet, /setPreviewAppearance\("source"\)/);
  assert.match(sheet, /value: "uv_checker"/);
  assert.match(sheet, /appearance=\{previewAppearance\}/);
  assert.match(sheet, /UV-сетка рисуется по координатам выбранного узла из готового GLB/);
  assert.match(sheet, /не является оценкой упаковки или редактором развёртки/);
  assert.match(viewer, /appearance === "uv_checker"/);
  assert.match(viewer, /floor\(vUv \* 16\.0\)/);
});

test("reference 84 binds one measured UV atlas to every verified LOD", () => {
  const lods = [
    { name: "SovaModel_LOD0" },
    { name: "SovaModel_LOD1" },
  ];
  const atlases = [
    { lod: "SovaModel_LOD0", triangle_area_pct: 72.5, degenerate_triangles: 0, out_of_bounds_vertices: 0 },
    { lod: "SovaModel_LOD1", triangle_area_pct: 68.1, degenerate_triangles: 1, out_of_bounds_vertices: 2 },
  ];
  assert.equal(gameReadyUvReportMatchesLods({ uv: true, uv_atlases: atlases }, lods, true), true);
  assert.equal(gameReadyUvReportMatchesLods({ uv: true, uv_atlases: atlases.slice(0, 1) }, lods, true), false);
  assert.equal(gameReadyUvReportMatchesLods({ uv: true, uv_atlases: [{ ...atlases[0], lod: "Other_LOD0" }, atlases[1]] }, lods, true), false);
  assert.equal(gameReadyUvReportMatchesLods({ uv: true, uv_atlases: [{ ...atlases[0], triangle_area_pct: Number.NaN }, atlases[1]] }, lods, true), false);
  assert.equal(gameReadyUvReportMatchesLods({ uv: false, uv_atlases: atlases }, lods, false), true);
  assert.equal(gameReadyUvReportMatchesLods({ uv: false, uv_atlases: [] }, lods, true), false);
  assert.match(project, /gameReadyUvReportMatchesLods\(/);
  assert.match(sheet, /result\.report\.uv \? result\.report\.uv_atlases\?\.map/);
});

test("reference 86 previews the exact exported collider without claiming physics", () => {
  assert.match(sheet, /result\?\.report\?\.collider\?\.name === previewLod/);
  assert.match(sheet, /setPreviewLod\(result\.report\?\.collider\?\.name \?\? null\)/);
  assert.match(sheet, /setPreviewAppearance\("mesh"\)/);
  assert.match(sheet, /именованный UCX-коллайдер из экспортного GLB/);
  assert.match(sheet, /не симуляция столкновений, массы или динамики/);
  assert.match(sheet, /result\.report\.uv && !previewIsCollider/);
});

test("project viewer exposes source, clay and wire modes with measured mesh stats", () => {
  assert.match(viewer, /ModelAppearance = "source" \| "clay" \| "mesh"/);
  assert.match(viewer, /onTopologyReport\?\.\(topology\?\.report \?\? null\)/);
  assert.match(project, /appearance=\{viewerAppearance\}/);
  assert.match(project, /\["source", ru \? "Материал"/);
  assert.match(project, /\["clay", ru \? "Белая"/);
  assert.match(project, /\["mesh", ru \? "Сетка"/);
  assert.match(project, /viewerTopology\.faces\.toLocaleString/);
});
