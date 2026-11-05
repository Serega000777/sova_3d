import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  applyExplodedPreview,
  verifiedAssemblyGeometryJob,
  verifiedAssemblyInspection,
} from "../src/lib/assembly-inspection.ts";

const panel = readFileSync(new URL("../src/components/AssemblyInspectionPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const identity = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

const manifest = {
  version_id: "scene-v1",
  component_count: 2,
  visible_component_count: 2,
  unique_geometry_count: 1,
  components: [
    { order: 1, node_id: "part", source_node_id: "part", name: "Bracket", parent_id: "assembly", instance_of: null, resolved_asset_id: "asset-1", effective_visible: true, world_transform: identity },
    { order: 2, node_id: "copy", source_node_id: "part", name: "Bracket copy", parent_id: "assembly", instance_of: "part", resolved_asset_id: "asset-1", effective_visible: true, world_transform: identity },
  ],
  bom: [{ source_node_id: "part", name: "Bracket", resolved_asset_id: "asset-1", quantity: 2, visible_quantity: 2, node_ids: ["part", "copy"] }],
  exploded_order: ["part", "copy"],
  structure_validated: true,
  constraints_status: "not_modeled",
  collision_status: "not_checked",
  limitations: ["stored order is not an assembly sequence"],
};

const geometry = {
  ok: true,
  version_id: "scene-v1",
  component_count: 2,
  constraints_status: "not_modeled",
  collision_status: "checked",
  scene_bbox_min_mm: [0, 0, 0],
  scene_bbox_max_mm: [50, 20, 10],
  components: [
    { node_id: "part", bbox_min_mm: [0, 0, 0], bbox_max_mm: [20, 20, 10] },
    { node_id: "copy", bbox_min_mm: [15, 0, 0], bbox_max_mm: [50, 20, 10] },
  ],
  envelope_overlaps: [{ node_a_id: "part", node_b_id: "copy", overlap_mm: [5, 10, 10] }],
  mesh_collisions: [{ node_a_id: "part", node_b_id: "copy", interference_mm3: 50, bbox_min_mm: [10, 5, 0], bbox_max_mm: [15, 15, 10] }],
  collision_unavailable_pairs: [],
};

test("reference 67 manifest is bound to exact version order instances and BOM", () => {
  assert.equal(verifiedAssemblyInspection(manifest, "scene-v1")?.bom[0]?.quantity, 2);
  assert.equal(verifiedAssemblyInspection(manifest, "other"), null);
  assert.equal(verifiedAssemblyInspection({ ...manifest, exploded_order: ["copy", "part"] }, "scene-v1"), null);
  assert.equal(verifiedAssemblyInspection({ ...manifest, bom: [{ ...manifest.bom[0], quantity: 1 }] }, "scene-v1"), null);
  assert.equal(verifiedAssemblyInspection({ ...manifest, components: [manifest.components[0], { ...manifest.components[1], resolved_asset_id: "other" }] }, "scene-v1"), null);
});

test("geometry result requires the accepted exact job workspace version and nodes", () => {
  const job = {
    id: "job-67",
    type: "inspect_assembly_geometry",
    status: "succeeded",
    workspace_id: "workspace-1",
    project_id: "project-1",
    project_version_id: "scene-v1",
    result: geometry,
  } as never;
  assert.equal(verifiedAssemblyGeometryJob(job, "job-67", "workspace-1", "scene-v1", ["part", "copy"])?.mesh_collisions[0]?.interference_mm3, 50);
  assert.equal(verifiedAssemblyGeometryJob(job, "other-job", "workspace-1", "scene-v1", ["part", "copy"]), null);
  assert.equal(verifiedAssemblyGeometryJob({ ...job, result: { ...geometry, collision_status: "checked", collision_unavailable_pairs: [{ node_a_id: "part", node_b_id: "copy", reason: "non_watertight" }] } } as never, "job-67", "workspace-1", "scene-v1", ["part", "copy"]), null);
  assert.equal(verifiedAssemblyGeometryJob(job, "job-67", "workspace-1", "scene-v1", ["part", "missing"]), null);
});

test("exploded preview offsets only display transforms and preserves the source scene", () => {
  const parts = [
    { id: "part", worldTransform: identity.map((row) => [...row]) },
    { id: "copy", worldTransform: identity.map((row) => [...row]) },
  ] as never;
  const exploded = applyExplodedPreview(parts, { order: ["part", "copy"], gapMm: 30 });
  assert.equal(exploded[0]?.worldTransform[2]?.[3], -15);
  assert.equal(exploded[1]?.worldTransform[2]?.[3], 15);
  assert.equal(parts[0]?.worldTransform[2]?.[3], 0);
  assert.deepEqual(applyExplodedPreview(parts, { order: ["part", "missing"], gapMm: 30 }), parts);
});

test("web scene inspector exposes canonical manifest bounded collision check and honest preview", () => {
  assert.match(studio, /verifiedAssemblyInspection\(value, activeVersionId\)/);
  assert.match(studio, /applyExplodedPreview\(mechanismSceneParts, explodedPreview\)/);
  assert.match(panel, /client\.inspectAssemblyGeometry\(versionId, `assembly-envelope:\$\{versionId\}`\)/);
  assert.match(panel, /verifiedAssemblyGeometryJob/);
  assert.match(panel, /Mate\/joint, движение, гравитация и прочность не моделируются/);
  assert.match(panel, /Порядок сохранённых узлов — это preview, а не инструкция монтажа/);
  assert.match(panel, /AABB — только broad phase/);
});
