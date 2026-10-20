import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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
  assert.match(sheet, /lods \? \[0\.5, 0\.2\] : \[\]/);
  assert.match(sheet, /Quad · \{ru \? "скоро" : "soon"\}/);
  assert.match(sheet, /проверяемая треугольная decimation/);
  assert.match(sheet, /Linking\.openURL\(result\.downloadUrl\)/);
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
