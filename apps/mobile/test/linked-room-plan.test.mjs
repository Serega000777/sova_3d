import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../src/WorkspaceShell.tsx", import.meta.url), "utf8");

test("reference 12 keeps the exact room plan and 3D model linked in one workspace", () => {
  assert.match(workspace, /План ↔ Модель/);
  assert.match(workspace, /flexDirection: swapped \? "row-reverse" : "row"/);
  assert.match(workspace, /\{sourceViewer\}/);
  assert.match(workspace, /\{viewer\}/);
  assert.match(workspace, /accessibilityLabel="Связать выделение"/);
  assert.match(project, /const \[linkedSelection, setLinkedSelection\] = useState\(true\)/);
  assert.match(project, /if \(linkedSelection\) setPlanSelection\(match\)/);
  assert.match(project, /if \(linkedSelection\) setModelPlanSelection\(next\)/);
});

test("reference 12 projects the active scene furniture into the same metric plan", () => {
  assert.match(project, /\.map\(planFootprintFromNode\)/);
  assert.match(project, /furniture=\{planFurniture\}/);
  assert.match(project, /linkedPlan=\{activeFloorPlan\}/);
  assert.match(project, /floor_plan_id: activeFloorPlan\.id/);
  assert.match(project, /client\.placeFurniture/);
});
