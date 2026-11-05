import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  exactPlanarHoles,
  fastenerAcceptedMatches,
  verifiedFastenerAssembly,
  verifiedFastenerFit,
  verifiedFastenerVersion,
} from "../src/lib/fastener-fit.ts";

const panel = readFileSync(new URL("../src/components/FastenerPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const requested = {
  workspace_id: "workspace-1",
  size: "M3",
  length_mm: 12,
  head: "socket_cap",
  drive: "hex",
  label: "Fastener M3×12",
} as const;

const fastener = {
  schema_version: 1,
  size: "M3",
  nominal_mm: 3,
  length_mm: 12,
  head: "socket_cap",
  drive: "hex",
  head_diameter_mm: 5.5,
  head_height_mm: 3,
  thread_geometry: "smooth_nominal_envelope",
  drive_recess_modeled: false,
  geometry_reference: "head_seat_z0",
} as const;

const accepted = {
  job: { job_id: "build-job", status: "queued", type: "execute_plan" },
  project_id: "fastener-project",
  fastener,
} as never;

const catalogItem = {
  size: "M3",
  nominal_mm: 3,
  clearance_mm: 3.4,
  tap_mm: 2.5,
  heat_set_mm: 4.2,
  socket_head_diameter_mm: 5.5,
} as const;

const hole = {
  id: "hole_1",
  diameterMm: 3.4,
  depthMm: 8,
  positionMm: [10, 20] as [number, number],
  faceAxis: "z" as const,
  faceSign: "+" as const,
};

test("reference 66 web selects only active exact planar holes for the exact version", () => {
  const stack = {
    version_id: "target-v1",
    operations: [
      { id: "hole_1", enabled: true, type: "add_hole", params: { diameter_mm: 3.4, depth_mm: 8, position_mm: [10, 20], face: { kind: "face_by_normal", axis: "z", sign: "+" } } },
      { id: "disabled", enabled: false, type: "add_hole", params: { diameter_mm: 3.4, position_mm: [0, 0], face: { kind: "face_by_normal", axis: "z", sign: "+" } } },
      { id: "mesh_guess", enabled: true, type: "mesh_hole", params: { diameter_mm: 3.4, position_mm: [0, 0], face: { kind: "face_by_normal", axis: "z", sign: "+" } } },
      { id: "curved", enabled: true, type: "add_hole", params: { diameter_mm: 3.4, position_mm: [0, 0], face: { kind: "surface", axis: "z", sign: "+" } } },
    ],
  } as never;
  assert.deepEqual(exactPlanarHoles(stack, "target-v1"), [hole]);
  assert.deepEqual(exactPlanarHoles(stack, "substituted-version"), []);
});

test("fastener build is bound to requested metadata workspace project and job", () => {
  assert.equal(fastenerAcceptedMatches(accepted, requested, "workspace-1", catalogItem), true);
  assert.equal(fastenerAcceptedMatches({ ...accepted, fastener: { ...fastener, size: "M4" } } as never, requested, "workspace-1", catalogItem), false);
  assert.equal(fastenerAcceptedMatches({ ...accepted, fastener: { ...fastener, nominal_mm: 4 } } as never, requested, "workspace-1", catalogItem), false);
  const job = {
    id: "build-job",
    type: "execute_plan",
    status: "succeeded",
    workspace_id: "workspace-1",
    project_id: "fastener-project",
    project_version_id: null,
    result: { version_id: "fastener-v1" },
  } as never;
  assert.equal(verifiedFastenerVersion(job, accepted, "workspace-1"), "fastener-v1");
  assert.equal(verifiedFastenerVersion({ ...job, project_id: "other" } as never, accepted, "workspace-1"), null);
});

test("fit report is bound to exact target fastener hole and measured clearance", () => {
  const report = {
    measured: { verdict: "sliding", max_penetration_mm: 0, min_clearance_mm: 0.2, interference_mm3: 0, b_inside_a_fraction: 1 },
    advice: { summary: "ok", recommendation: null, fix: null, numbers: {} },
    wanted: "clearance",
    fastener: {
      schema_version: 1,
      hole_operation_id: "hole_1",
      hole_diameter_mm: 3.4,
      hole_depth_mm: 8,
      radial_clearance_mm: 0.2,
      engagement_mm: 8,
      head_seated: true,
      geometry_compatible: true,
      fastener,
      limitations: ["smooth envelope", "no torque"],
    },
  };
  const job = {
    id: "fit-job",
    type: "fit_test",
    status: "succeeded",
    workspace_id: "workspace-1",
    project_id: "target-project",
    project_version_id: "target-v1",
    result: { fit_test_id: "fit-1", version_a_id: "target-v1", version_b_id: "fastener-v1", report },
  } as never;
  assert.equal(verifiedFastenerFit(job, "fit-job", "workspace-1", "target-v1", "fastener-v1", hole, requested, fastener)?.fitTestId, "fit-1");
  assert.equal(verifiedFastenerFit(job, "substituted-job", "workspace-1", "target-v1", "fastener-v1", hole, requested, fastener), null);
  assert.equal(verifiedFastenerFit({ ...job, result: { ...job.result, version_b_id: "other" } } as never, "fit-job", "workspace-1", "target-v1", "fastener-v1", hole, requested, fastener), null);
  assert.equal(verifiedFastenerFit({ ...job, result: { ...job.result, report: { ...report, fastener: { ...report.fastener, radial_clearance_mm: 99 } } } } as never, "fit-job", "workspace-1", "target-v1", "fastener-v1", hole, requested, fastener), null);
  assert.equal(verifiedFastenerFit({ ...job, result: { ...job.result, report: { ...report, fastener: { ...report.fastener, fastener: null } } } } as never, "fit-job", "workspace-1", "target-v1", "fastener-v1", hole, requested, fastener), null);
});

test("only a child scene retaining the fastener as its own node is accepted", () => {
  const scene = {
    version_id: "assembly-v2",
    parent_version_id: "target-v1",
    nodes: [
      { id: "assembly", kind: "group", parent_id: null, asset_id: null },
      { id: "part_a", kind: "object", parent_id: "assembly", asset_id: "asset-a" },
      { id: "fastener", kind: "object", parent_id: "assembly", asset_id: "asset-b" },
    ],
  } as never;
  assert.equal(verifiedFastenerAssembly(scene, "target-v1")?.version_id, "assembly-v2");
  assert.equal(verifiedFastenerAssembly({ ...scene, nodes: [{ id: "assembly" }, { id: "part_a" }, { id: "part_b" }] } as never, "target-v1"), null);
  assert.equal(verifiedFastenerAssembly({ ...scene, parent_version_id: "other" } as never, "target-v1"), null);
});

test("web UI runs the exact two-job flow and states the engineering limits", () => {
  assert.match(panel, /client\.getOperationStack\(versionId\)/);
  assert.match(panel, /client\.createFastener\(requested, crypto\.randomUUID\(\)\)/);
  assert.match(panel, /client\.startFastenerFit\(sourceVersionId/);
  assert.match(panel, /verifiedFastenerFit/);
  assert.match(panel, /client\.createFitAssembly/);
  assert.match(panel, /Резьба, шлиц, момент затяжки, преднатяг, прочность и сертификация не моделируются/);
  assert.match(studio, /tool === "fastener"/);
  assert.match(studio, /workspaceId=\{project\.workspace_id\}/);
  assert.match(studio, /setActiveVersion\(await client\.getVersion\(scene\.version_id\)\)/);
});
