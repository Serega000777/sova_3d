import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const tree = readFileSync(new URL("../src/SceneTreeSheet.tsx", import.meta.url), "utf8");
const layers = readFileSync(new URL("../src/MeshLayersSheet.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 09 edits a server-backed scene hierarchy as a new immutable version", () => {
  assert.match(tree, /client\s*\.getScene\(versionId\)/);
  assert.match(tree, /client\.updateScene\(versionId, body\)/);
  assert.match(tree, /groupSelected/);
  assert.match(tree, /ungroupSelected/);
  assert.match(tree, /duplicateInstance/);
  assert.match(tree, /makeUnique/);
  assert.match(tree, /visible: !item\.visible/);
  assert.match(tree, /await onSaved\(next\.version_id\)/);
  assert.match(project, /selectedSceneNodeId/);
});

test("reference 09 reorders and disables real mesh modifiers before server rebuild", () => {
  assert.match(layers, /client\s*\.getMeshModifierStack\(versionId\)/);
  assert.match(layers, /const move = \(index: number, offset: -1 \| 1\)/);
  assert.match(layers, /enabled: !entry\.enabled/);
  assert.match(layers, /client\.updateMeshModifierStack\(versionId/);
  assert.match(layers, /modifiers: entries\.map\(\(\{ id, enabled \}\)/);
  assert.match(layers, /await onJob\(accepted\.job_id\)/);
  assert.match(layers, /source version stays unchanged/);
});
