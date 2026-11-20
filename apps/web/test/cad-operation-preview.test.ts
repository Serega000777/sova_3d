import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { cadOperationFacts, cadOperationFeaturePreview } from "../src/lib/cad-operation-preview.ts";

const hole = {
  id: "hole_1",
  type: "add_hole",
  params: {
    face: { kind: "face_by_normal", axis: "z", sign: "+" },
    position_mm: [12, -8],
    diameter_mm: 5,
    depth_mm: 14,
    target: "body",
  },
};

test("exact face-normal holes and threads produce bounded semantic preview facts", () => {
  assert.deepEqual(cadOperationFeaturePreview(hole), {
    operationId: "hole_1",
    kind: "hole",
    axis: "z",
    sign: "+",
    positionMm: [12, -8],
    diameterMm: 5,
  });
  assert.deepEqual(cadOperationFacts(hole), {
    mode: "blind",
    depthMm: 14,
    face: "z+",
    positionMm: [12, -8],
    direction: "normal_to_face",
    target: "body",
  });
  assert.equal(cadOperationFacts({ ...hole, params: { ...hole.params, depth_mm: null } })?.mode, "through");
  assert.equal(cadOperationFeaturePreview({
    ...hole,
    id: "thread_1",
    type: "add_internal_thread",
    params: { ...hole.params, diameter_mm: undefined, major_diameter_mm: 6 },
  })?.kind, "thread");
});

test("ambiguous or malformed topology facts fail closed", () => {
  assert.equal(cadOperationFeaturePreview({ ...hole, type: "fillet" }), null);
  assert.equal(cadOperationFeaturePreview({ ...hole, params: { ...hole.params, face: { kind: "face_by_id", id: "Face7" } } }), null);
  assert.equal(cadOperationFeaturePreview({ ...hole, params: { ...hole.params, position_mm: [12, Number.NaN] } }), null);
  assert.equal(cadOperationFeaturePreview({ ...hole, params: { ...hole.params, diameter_mm: 0 } }), null);
  assert.equal(cadOperationFacts({ ...hole, params: { ...hole.params, target: "" } }), null);
  assert.equal(cadOperationFacts({ ...hole, params: { ...hole.params, depth_mm: -1 } }), null);
});

test("web history selection drives the exact viewer ring and semantic detail card", () => {
  const panel = readFileSync(new URL("../src/components/OperationStackPanel.tsx", import.meta.url), "utf8");
  const viewer = readFileSync(new URL("../src/components/ModelViewer.tsx", import.meta.url), "utf8");
  const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
  assert.match(panel, /cadOperationFeaturePreview\(previewEntry\)/);
  assert.match(panel, /onSelectionChange\(next \? featurePreview : null\)/);
  assert.match(panel, /operationFacts\.positionMm/);
  assert.match(viewer, /operationPreview\.sign === "\+"/);
  assert.match(viewer, /bounds\.max\[operationPreview\.axis\]/);
  assert.match(viewer, /<torusGeometry args=\{\[radiusMm/);
  assert.match(studio, /operationPreview=\{cadOperationPreview\}/);
  assert.match(studio, /onSelectionChange=\{setCadOperationPreview\}/);
});
