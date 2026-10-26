import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { cadOperationFeaturePreview } from "../src/cad-operation-preview.ts";

test("maps exact hole and thread operations to an honest viewport marker", () => {
  assert.deepEqual(cadOperationFeaturePreview({
    id: "hole_1",
    type: "add_hole",
    params: {
      face: { kind: "face_by_normal", axis: "z", sign: "+" },
      position_mm: [12, 18],
      diameter_mm: 5,
    },
  }), {
    operationId: "hole_1",
    kind: "hole",
    axis: "z",
    sign: "+",
    positionMm: [12, 18],
    diameterMm: 5,
  });
  assert.equal(cadOperationFeaturePreview({
    id: "fillet_1",
    type: "fillet",
    params: { radius_mm: 2 },
  }), null);
});

test("rejects ambiguous or malformed feature locations", () => {
  assert.equal(cadOperationFeaturePreview({
    id: "hole_1",
    type: "add_hole",
    params: {
      face: { kind: "selected_face", axis: "z", sign: "+" },
      position_mm: [12, 18],
      diameter_mm: 5,
    },
  }), null);
  assert.equal(cadOperationFeaturePreview({
    id: "thread_1",
    type: "add_internal_thread",
    params: {
      face: { kind: "face_by_normal", axis: "x", sign: "-" },
      position_mm: [12, Number.NaN],
      major_diameter_mm: 6,
    },
  }), null);
});

test("history selection is wired to the real model viewer", () => {
  const screen = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const sheet = readFileSync(new URL("../src/CadHistorySheet.tsx", import.meta.url), "utf8");
  const viewer = readFileSync(new URL("../src/ModelViewer.tsx", import.meta.url), "utf8");
  assert.match(screen, /operationPreview=\{cadOperationPreview\}/);
  assert.match(screen, /onSelectionChange=\{setCadOperationPreview\}/);
  assert.match(screen, /setCadOperationPreview\(null\)/);
  assert.match(sheet, /Показать на модели/);
  assert.match(sheet, /Object\.fromEntries\(editable\.map/);
  assert.match(viewer, /new THREE\.TorusGeometry/);
});
