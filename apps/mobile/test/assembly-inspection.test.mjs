import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseGeometryInspection } from "../src/assembly-inspection.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/AssemblyInspectionSheet.tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("reference 67 reads the canonical server assembly manifest", () => {
  assert.match(client, /inspectAssembly\(versionId: string\)/);
  assert.match(client, /assembly-inspection/);
  assert.match(sheet, /client\.inspectAssembly\(versionId\)/);
  assert.match(sheet, /inspection\.bom\.map/);
  assert.match(project, /Сборка деталей/);
});

test("the exploded preview uses the exact server order and reversible world transforms", () => {
  assert.match(sheet, /inspection\.exploded_order/);
  assert.match(project, /const rank = new Map\(explodedPreview\.order/);
  assert.match(project, /worldTransform\[2\]!\[3\] \+=/);
  assert.match(project, /displayedSceneParts/);
  assert.match(sheet, /Собрать preview/);
});

test("geometry inspection reports only exact positive-volume collisions", () => {
  assert.match(client, /inspectAssemblyGeometry/);
  assert.match(sheet, /waitForJob/);
  assert.match(sheet, /parseGeometryInspection/);
  assert.match(sheet, /positive Manifold intersection volume/);
  assert.match(sheet, /mesh_collisions\.map/);
  assert.match(sheet, /collision_unavailable_pairs\.map/);
});

test("the assembly UI keeps unsupported verification boundaries explicit", () => {
  assert.match(sheet, /Связи mate\/joint, движение и физика не моделируются/);
  assert.match(sheet, /не выдаётся за инструкцию монтажа/);
  assert.match(client, /no inferred joints or collision claims/);
});

test("exact collision result parser rejects forged or partial evidence", () => {
  const valid = {
    ok: true,
    component_count: 2,
    scene_bbox_min_mm: [0, 0, 0],
    scene_bbox_max_mm: [10, 10, 10],
    envelope_overlaps: [{ node_a_id: "a", node_b_id: "b", overlap_mm: [2, 3, 4] }],
    mesh_collisions: [{
      node_a_id: "a",
      node_b_id: "b",
      interference_mm3: 12,
      bbox_min_mm: [2, 2, 2],
      bbox_max_mm: [4, 5, 6],
    }],
    collision_unavailable_pairs: [],
    collision_status: "checked",
  };
  assert.deepEqual(parseGeometryInspection(valid, ["a", "b"]), valid);
  assert.equal(parseGeometryInspection(valid, ["a", "other"]), null);
  assert.equal(parseGeometryInspection(valid, ["a", "b", "c"]), null);
  assert.equal(parseGeometryInspection({ ...valid, collision_status: "unavailable" }), null);
  assert.equal(parseGeometryInspection({ ...valid, mesh_collisions: [{ ...valid.mesh_collisions[0], interference_mm3: 0 }] }), null);
  assert.equal(parseGeometryInspection({ ...valid, mesh_collisions: [{ ...valid.mesh_collisions[0], node_b_id: "other" }] }), null);
  assert.equal(parseGeometryInspection({ ...valid, envelope_overlaps: [{ ...valid.envelope_overlaps[0], overlap_mm: [2, -1, 4] }] }), null);
});

test("unavailable collision evidence names every affected broad-phase pair", () => {
  const unavailable = {
    ok: true,
    component_count: 2,
    scene_bbox_min_mm: [0, 0, 0],
    scene_bbox_max_mm: [10, 10, 10],
    envelope_overlaps: [{ node_a_id: "a", node_b_id: "b", overlap_mm: [2, 3, 4] }],
    mesh_collisions: [],
    collision_unavailable_pairs: [{
      node_a_id: "a",
      node_b_id: "b",
      reason: "non_watertight",
    }],
    collision_status: "unavailable",
  };
  assert.deepEqual(parseGeometryInspection(unavailable), unavailable);
  assert.equal(parseGeometryInspection({ ...unavailable, collision_unavailable_pairs: [] }), null);
  assert.equal(parseGeometryInspection({ ...unavailable, collision_unavailable_pairs: [{ ...unavailable.collision_unavailable_pairs[0], reason: "unknown" }] }), null);
});
