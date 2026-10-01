/** T-234: the topology behind vertex/edge/face selection, the grid and symmetry. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applySelection,
  buildLookup,
  buildTopology,
  componentAtHit,
  defaultGrid,
  mirrorSelection,
  overlayEdges,
  selectInRect,
  snapPoint,
  suggestGridStep,
  symmetricPoints,
  topologyNotice,
  verticesOf,
} from "../src/topology.ts";

// Unit cube as an unindexed triangle soup, like an STL: 12 triangles, 36 corners.
function cubeSoup(): number[] {
  const v = [
    [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
  ];
  const tris = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
    [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ];
  return tris.flatMap((t) => t.flatMap((i) => v[i] as number[]));
}

test("welding turns a 36-corner STL cube into 8 vertices, 18 edges, 12 faces", () => {
  const topology = buildTopology(cubeSoup(), null);
  assert.equal(topology.report.vertices, 8);
  assert.equal(topology.report.faces, 12);
  assert.equal(topology.report.edges, 18);
  assert.equal(topology.report.boundaryEdges, 0);
  assert.equal(topology.report.status, "stable");
  assert.equal(topology.report.sourceIndexed, false);
});

test("an open mesh reports its boundary instead of claiming stability", () => {
  const soup = cubeSoup().slice(0, 33 * 3 - 3 * 3); // drop the last three triangles
  const topology = buildTopology(soup, null);
  assert.equal(topology.report.status, "open");
  assert.ok(topology.report.boundaryEdges > 0);
  assert.match(topologyNotice(topology.report, "en") ?? "", /not watertight/);
  assert.match(topologyNotice(topology.report, "ru") ?? "", /не замкнута/);
});

test("an empty or fully degenerate mesh has no stable topology", () => {
  const empty = buildTopology([], null);
  assert.equal(empty.report.status, "none");
  const flat = buildTopology([0, 0, 0, 0, 0, 0, 0, 0, 0], null);
  assert.equal(flat.report.status, "none");
  assert.equal(flat.report.degenerateFaces, 1);
  assert.match(topologyNotice(flat.report, "en") ?? "", /no stable topology/);
});

test("indexed sources keep their index and need no unindexed warning", () => {
  const positions = [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0];
  const topology = buildTopology(positions, [0, 1, 2, 1, 3, 2]);
  assert.equal(topology.report.sourceIndexed, true);
  assert.equal(topology.report.vertices, 4);
  assert.equal(topology.report.faces, 2);
  assert.equal(topology.report.edges, 5);
  assert.equal(topology.report.boundaryEdges, 4);
});

test("a picked point resolves to the nearest vertex, edge and the face itself", () => {
  const topology = buildTopology(cubeSoup(), null);
  // Triangle 0 is the bottom face corner (0,0,0)-(1,1,0)-(1,0,0); click near corner (1,0,0).
  const hit = { sourceFace: 0, point: [0.9, 0.05, 0] as const };
  const vertex = componentAtHit(topology, "vertex", hit);
  assert.deepEqual([...topology.positions.slice((vertex as number) * 3, (vertex as number) * 3 + 3)], [1, 0, 0]);
  const edge = componentAtHit(topology, "edge", hit) as number;
  const ends = [topology.edges[edge * 2], topology.edges[edge * 2 + 1]].map((id) => [
    ...topology.positions.slice((id as number) * 3, (id as number) * 3 + 3),
  ]);
  assert.deepEqual(ends.map((p) => p[1]).sort(), [0, 0]); // the y=0 edge from (0,0,0) to (1,0,0)
  assert.equal(componentAtHit(topology, "face", hit), 0);
});

test("a source triangle dropped as degenerate selects nothing", () => {
  const soup = [...cubeSoup(), 0, 0, 0, 0, 0, 0, 0, 0, 0];
  const topology = buildTopology(soup, null);
  assert.equal(componentAtHit(topology, "face", { sourceFace: 12, point: [0, 0, 0] }), null);
});

test("selection modes replace, add, remove and toggle", () => {
  const start = new Set([1, 2]);
  assert.deepEqual([...applySelection(start, [3], "replace")], [3]);
  assert.deepEqual([...applySelection(start, [3], "add")].sort(), [1, 2, 3]);
  assert.deepEqual([...applySelection(start, [2], "remove")], [1]);
  assert.deepEqual([...applySelection(start, [2, 4], "toggle")].sort(), [1, 4]);
  assert.deepEqual([...start], [1, 2]); // the input is never mutated
});

test("box selection takes only components fully inside and visible", () => {
  const topology = buildTopology(cubeSoup(), null);
  const screen = new Float32Array(topology.report.vertices * 2);
  const visible = new Uint8Array(topology.report.vertices).fill(1);
  for (let v = 0; v < topology.report.vertices; v += 1) {
    screen[v * 2] = topology.positions[v * 3] as number; // x
    screen[v * 2 + 1] = topology.positions[v * 3 + 2] as number; // z
  }
  const rect = { minX: -0.1, minY: -0.1, maxX: 1.1, maxY: 0.1 }; // the bottom row, z = 0
  const vertices = selectInRect(topology, "vertex", screen, visible, rect);
  assert.equal(vertices.length, 4);
  const faces = selectInRect(topology, "face", screen, visible, rect);
  assert.equal(faces.length, 2); // the bottom face's two triangles; side faces reach z = 1
  visible[0] = 0;
  assert.equal(selectInRect(topology, "vertex", screen, visible, rect).length, 3);
  const edgeVertices = verticesOf(topology, "face", faces);
  assert.equal(edgeVertices.length, 4);
});

test("large meshes draw a bounded edge subset but keep every open edge", () => {
  const topology = buildTopology(cubeSoup(), null);
  assert.equal(overlayEdges(topology).length, topology.report.edges);
  const small = overlayEdges(topology, 6);
  assert.ok(small.length <= 6);
  assert.equal(new Set(small).size, small.length);
  // an open mesh must keep its boundary edges even over budget
  const open = buildTopology(cubeSoup().slice(0, 27 * 3), null);
  const boundary = [...open.edgeUse].filter((u) => u === 1).length;
  assert.ok(boundary > 0);
  const kept = overlayEdges(open, 2);
  const keptBoundary = kept.filter((e) => open.edgeUse[e] === 1).length;
  assert.equal(keptBoundary, boundary);
});

test("grid snapping rounds to the increment and stays inert when off", () => {
  const grid = { ...defaultGrid(), step_mm: 5, snap: true };
  assert.deepEqual(snapPoint([12.4, -7.6, 2.4], grid), [10, -10, 0]);
  assert.deepEqual(snapPoint([12.4, -7.6, 2.4], { step_mm: 5, snap: false }), [12.4, -7.6, 2.4]);
  assert.deepEqual(snapPoint([1.3, 0, 0], { step_mm: 0, snap: true }), [1.3, 0, 0]);
  assert.deepEqual(snapPoint([0.26, 0, 0], { step_mm: 0.25, snap: true }), [0.25, 0, 0]);
});

test("a sensible grid step is suggested for tiny and huge parts", () => {
  assert.equal(suggestGridStep(20), 1);
  assert.equal(suggestGridStep(100), 5);
  assert.equal(suggestGridStep(2000), 100);
  assert.equal(suggestGridStep(1), 0.1);
});

test("symmetry mirrors across each enabled plane through the chosen origin", () => {
  const grid = defaultGrid();
  assert.equal(symmetricPoints([3, 4, 5], grid).length, 1);
  grid.symmetry.x = true;
  assert.deepEqual(symmetricPoints([3, 4, 5], grid), [[3, 4, 5], [-3, 4, 5]]);
  grid.symmetry.y = true;
  assert.equal(symmetricPoints([3, 4, 5], grid).length, 4);
  grid.symmetry.z = true;
  assert.equal(symmetricPoints([3, 4, 5], grid).length, 8);
  grid.symmetry_origin = [10, 0, 0];
  assert.ok(symmetricPoints([3, 4, 5], grid).some((p) => p[0] === 17));
  // a point already on the plane does not duplicate
  assert.equal(symmetricPoints([0, 4, 5], { ...defaultGrid(), symmetry: { x: true, y: false, z: false } }).length, 1);
});

// Octahedron around the origin: symmetric under a mirror in x, y and z.
function octahedron(): number[] {
  const v: Record<string, number[]> = {
    px: [1, 0, 0], nx: [-1, 0, 0], py: [0, 1, 0], ny: [0, -1, 0], pz: [0, 0, 1], nz: [0, 0, -1],
  };
  const tris = [
    ["px", "py", "pz"], ["py", "nx", "pz"], ["nx", "ny", "pz"], ["ny", "px", "pz"],
    ["py", "px", "nz"], ["nx", "py", "nz"], ["ny", "nx", "nz"], ["px", "ny", "nz"],
  ];
  return tris.flatMap((t) => t.flatMap((k) => v[k] as number[]));
}

test("mirrored selection follows the model's own symmetry for every component kind", () => {
  const topology = buildTopology(octahedron(), null);
  const lookup = buildLookup(topology);
  const grid = defaultGrid();
  grid.symmetry.x = true;
  const find = (x: number, y: number, z: number) => {
    for (let v = 0; v < topology.report.vertices; v += 1) {
      const p = topology.positions;
      if (p[v * 3] === x && p[v * 3 + 1] === y && p[v * 3 + 2] === z) return v;
    }
    throw new Error("vertex not found");
  };
  const right = find(1, 0, 0);
  assert.deepEqual(
    mirrorSelection(topology, lookup, "vertex", [right], grid),
    [right, find(-1, 0, 0)].sort((a, b) => a - b),
  );
  // face 0 is px-py-pz; its x-mirror is nx-py-pz (face 1)
  assert.deepEqual(mirrorSelection(topology, lookup, "face", [0], grid), [0, 1]);
  const edge = componentAtHit(topology, "edge", { sourceFace: 0, point: [0.5, 0.5, 0.01] }) as number;
  assert.equal(mirrorSelection(topology, lookup, "edge", [edge], grid).length, 2);
  grid.symmetry.y = true;
  grid.symmetry.z = true;
  assert.equal(mirrorSelection(topology, lookup, "face", [0], grid).length, 8);
});

test("a face whose mirror is not on the mesh stays alone", () => {
  const topology = buildTopology(cubeSoup(), null); // the cube's diagonals are not mirror images
  const grid = { ...defaultGrid(), symmetry_origin: [0.5, 0.5, 0.5] as [number, number, number] };
  grid.symmetry.x = true;
  assert.deepEqual(mirrorSelection(topology, buildLookup(topology), "face", [0], grid), [0]);
});

test("a model that is not symmetric simply keeps the picked component", () => {
  const topology = buildTopology([0, 0, 0, 1, 0, 0, 0, 3, 0], null);
  const lookup = buildLookup(topology);
  const grid = defaultGrid();
  grid.symmetry.x = true;
  assert.deepEqual(mirrorSelection(topology, lookup, "vertex", [0], grid), [0]);
});
