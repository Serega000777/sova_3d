import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  movePaintLayerOrder,
  paintDraftMatchesContext,
  paintLayerSummaries,
  removePaintStroke,
} from "../src/lib/paint-workflow.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("paint drafts are bound to the exact immutable version and selected scene node", () => {
  assert.equal(paintDraftMatchesContext("v1", null, "v1", null), true);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v1", "chair"), true);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v2", "chair"), false);
  assert.equal(paintDraftMatchesContext("v1", "chair", "v1", "table"), false);
  assert.equal(paintDraftMatchesContext(null, null, "v1", null), false);
});

test("draft stroke removal is immutable and bounded", () => {
  assert.deepEqual(removePaintStroke(["a", "b", "c"], 1), ["a", "c"]);
  assert.deepEqual(removePaintStroke(["a", "b"], -1), ["a", "b"]);
  assert.deepEqual(removePaintStroke(["a", "b"], 5), ["a", "b"]);
});

test("saved layer evidence rejects malformed provenance and reorders complete unique names", () => {
  const provenance = {
    paint: {
      strokes: [
        { colour: "#112233", opacity: 0.5 },
        { colour: "#445566" },
      ],
      layers: [
        { name: "Base", stroke_start: 0, stroke_count: 1 },
        { name: "Detail", stroke_start: 1, stroke_count: 1 },
      ],
    },
  };
  const layers = paintLayerSummaries(provenance);
  assert.deepEqual(layers, [
    { name: "Base", strokeCount: 1, colours: ["#112233"], materialIds: [], opacities: [0.5] },
    { name: "Detail", strokeCount: 1, colours: ["#445566"], materialIds: [], opacities: [1] },
  ]);
  assert.deepEqual(movePaintLayerOrder(layers, 0, 1), ["Detail", "Base"]);
  assert.equal(movePaintLayerOrder(layers, 0, -1), null);
  assert.deepEqual(
    paintLayerSummaries({ paint: { ...provenance.paint, strokes: [{ colour: "forged" }] } }),
    [],
  );
});

test("web studio sends named opacity layers through the exact source-bound typed routes", () => {
  assert.match(studio, /paintDraftMatchesContext\(/);
  assert.match(studio, /opacity: stroke\.opacity/);
  assert.match(studio, /layer_name: layerName/);
  assert.match(studio, /scene_node_id: sourceSceneNodeId/);
  assert.match(studio, /client\.reorderPaintLayers\(sourceVersionId, layerOrder, sourceSceneNodeId\)/);
  assert.match(studio, /removePaintStroke\(current, index\)/);
});
