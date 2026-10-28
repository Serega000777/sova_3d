import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
const editSheet = readFileSync(new URL("../src/EditModeSheet.tsx", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../src/EditModeSheet.tsx", import.meta.url), "utf8");

test("reference 08 exposes touch vertex, edge and face editing with exact operations", () => {
  assert.match(sheet, /Выдавить/);
  assert.match(sheet, /Фаска/);
  assert.match(sheet, /Lasso select/);
  assert.match(project, /op: "extrude"/);
  assert.match(project, /op: "bevel_edges"/);
  assert.match(project, /op: "delete_faces"/);
  assert.match(project, /client\.editMesh\(active\.id/);
  assert.match(project, /await headAfterJob\(job\)/);
  assert.match(sheet, /Math\.abs\(magnitude\) >= 1e-6/);
  assert.match(sheet, /Math\.abs\(magnitude\) <= MAX_EXTRUSION_MM/);
});

test("reference 08 transform gizmo is axis constrained, bounded and grid aware", () => {
  assert.match(viewer, /makeTransformGizmo/);
  assert.match(viewer, /gizmoPickProxies/);
  assert.match(viewer, /axis === "x" \|\| axis === "y" \|\| axis === "z"/);
  assert.match(viewer, /Math\.min\(1000, Math\.max\(10, raw\)\)/);
  assert.match(viewer, /Math\.min\(359, Math\.max\(-359, raw\)\)/);
  assert.match(viewer, /value = snapPoint\(point, grid\)/);
  assert.match(project, /activeEditOperation=\{editOperation\}/);
  assert.match(project, /onEditMagnitudeChange=\{setEditMagnitude\}/);
});

test("G06 states the extrusion direction and keeps preview evidence honest", () => {
  assert.match(editSheet, /operation === "extrude"/);
  assert.match(editSheet, /Выдавливание по нормали/);
  assert.match(editSheet, /Знак расстояния задаёт направление вдоль нормали выбранных граней/);
  assert.match(editSheet, /viewport показывает выделение и расстояние, а не готовую экструдированную форму/);
  assert.match(project, /distance_mm: editMagnitude/);
  assert.match(project, /await headAfterJob\(job\)/);
});
