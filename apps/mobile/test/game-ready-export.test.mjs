import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseLodRatios } from "../src/game-ready.ts";

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

test("project viewer exposes source, clay and wire modes with measured mesh stats", () => {
  assert.match(viewer, /ModelAppearance = "source" \| "clay" \| "mesh"/);
  assert.match(viewer, /onTopologyReport\?\.\(topology\?\.report \?\? null\)/);
  assert.match(project, /appearance=\{viewerAppearance\}/);
  assert.match(project, /\["source", ru \? "Материал"/);
  assert.match(project, /\["clay", ru \? "Белая"/);
  assert.match(project, /\["mesh", ru \? "Сетка"/);
  assert.match(project, /viewerTopology\.faces\.toLocaleString/);
});
