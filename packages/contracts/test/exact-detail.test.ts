import assert from "node:assert/strict";
import test from "node:test";

import {
  chamferSpec,
  circularPatternSpec,
  exactHoleSpec,
  filletSpec,
  linearPatternSpec,
  mirrorSpec,
  shellSpec,
} from "../src/exact-detail.ts";

test("exact hole parses RU decimals into canonical millimetres", () => {
  assert.deepEqual(
    exactHoleSpec({
      axis: "y",
      sign: "-",
      positionU: " 12,5 ",
      positionV: "-3,25",
      diameter: "6,4",
      through: false,
      depth: "18,75",
    }),
    {
      spec: {
        face: { kind: "face_by_normal", axis: "y", sign: "-" },
        position_mm: [12.5, -3.25],
        diameter_mm: 6.4,
        depth_mm: 18.75,
      },
      issue: null,
    },
  );
});

test("through hole ignores a stale depth field", () => {
  assert.deepEqual(
    exactHoleSpec({
      axis: "z",
      sign: "+",
      positionU: "0",
      positionV: "0",
      diameter: "5",
      through: true,
      depth: "not a number",
    }),
    {
      spec: {
        face: { kind: "face_by_normal", axis: "z", sign: "+" },
        position_mm: [0, 0],
        diameter_mm: 5,
        depth_mm: null,
      },
      issue: null,
    },
  );
});

test("exact hole fails closed for malformed coordinates and dimensions", () => {
  const base = {
    axis: "x" as const,
    sign: "+" as const,
    positionU: "0",
    positionV: "0",
    diameter: "5",
    through: false,
    depth: "10",
  };

  assert.equal(exactHoleSpec({ ...base, positionU: "" }).issue, "invalid_position");
  assert.equal(exactHoleSpec({ ...base, positionV: "Infinity" }).issue, "invalid_position");
  assert.equal(exactHoleSpec({ ...base, diameter: "0" }).issue, "invalid_diameter");
  assert.equal(exactHoleSpec({ ...base, diameter: "NaN" }).issue, "invalid_diameter");
  assert.equal(exactHoleSpec({ ...base, depth: "-1" }).issue, "invalid_depth");
  assert.equal(exactHoleSpec({ ...base, diameter: "10000.1" }).issue, "invalid_diameter");
  assert.equal(exactHoleSpec({ ...base, depth: "10001" }).issue, "invalid_depth");
});

test("exact shell parses RU decimals into canonical millimetres", () => {
  assert.deepEqual(shellSpec({ thickness: " 2,5 ", openFace: false, axis: "z", sign: "+" }), {
    spec: { thickness_mm: 2.5 },
    issue: null,
  });
  assert.deepEqual(shellSpec({ thickness: "10000", openFace: false, axis: "z", sign: "+" }), {
    spec: { thickness_mm: 10_000 },
    issue: null,
  });
});

test("exact shell maps an optional axis face into the canonical open-face selector", () => {
  assert.deepEqual(shellSpec({ thickness: "3", openFace: true, axis: "y", sign: "-" }), {
    spec: {
      thickness_mm: 3,
      open_face: { kind: "face_by_normal", axis: "y", sign: "-" },
    },
    issue: null,
  });
  assert.deepEqual(
    shellSpec({ thickness: "3", openFace: false, axis: "bad" as "x", sign: "?" as "+" }),
    { spec: { thickness_mm: 3 }, issue: null },
  );
});

test("exact shell fails closed for a malformed requested opening face", () => {
  assert.equal(
    shellSpec({ thickness: "3", openFace: "yes" as never, axis: "z", sign: "+" }).issue,
    "invalid_open_face",
  );
  assert.equal(
    shellSpec({ thickness: "3", openFace: true, axis: "bad" as "x", sign: "+" }).issue,
    "invalid_open_face",
  );
  assert.equal(
    shellSpec({ thickness: "3", openFace: true, axis: "z", sign: "?" as "+" }).issue,
    "invalid_open_face",
  );
});

test("exact shell fails closed for malformed or out-of-range thickness", () => {
  for (const thickness of ["", " ", "not a number", "NaN", "Infinity", "-Infinity", "0", "-1", "10000.1"]) {
    assert.deepEqual(shellSpec({ thickness, openFace: false, axis: "z", sign: "+" }), {
      spec: null,
      issue: "invalid_thickness",
    });
  }
});

test("exact fillet supports all and parallel symbolic edge selectors", () => {
  assert.deepEqual(
    filletSpec({ edges: { kind: "all_edges" }, radius: " 2,5 " }),
    {
      spec: { edges: { kind: "all_edges" }, radius_mm: 2.5 },
      issue: null,
    },
  );
  assert.deepEqual(
    filletSpec({
      edges: { kind: "edges_parallel_to", axis: "z", outer: true },
      radius: "10000",
    }),
    {
      spec: {
        edges: { kind: "edges_parallel_to", axis: "z", outer: true },
        radius_mm: 10_000,
      },
      issue: null,
    },
  );
});

test("exact chamfer maps an axis/sign face into edges_of_face", () => {
  assert.deepEqual(
    chamferSpec({
      edges: { kind: "edges_of_face", axis: "y", sign: "-" },
      distance: "1.25",
    }),
    {
      spec: {
        edges: {
          kind: "edges_of_face",
          face: { kind: "face_by_normal", axis: "y", sign: "-" },
        },
        distance_mm: 1.25,
      },
      issue: null,
    },
  );
});

test("exact fillet and chamfer fail closed for malformed dimensions", () => {
  const edges = { kind: "all_edges" as const };
  for (const value of ["", " ", "not a number", "NaN", "Infinity", "0", "-1", "10000.1"]) {
    assert.deepEqual(filletSpec({ edges, radius: value }), {
      spec: null,
      issue: "invalid_radius",
    });
    assert.deepEqual(chamferSpec({ edges, distance: value }), {
      spec: null,
      issue: "invalid_distance",
    });
  }
});

test("edge selector rejects outer outside parallel mode", () => {
  assert.deepEqual(
    filletSpec({
      edges: { kind: "all_edges", outer: false } as never,
      radius: "2",
    }),
    { spec: null, issue: "invalid_edges" },
  );
  assert.deepEqual(
    chamferSpec({
      edges: { kind: "edges_of_face", axis: "x", sign: "+", outer: true } as never,
      distance: "2",
    }),
    { spec: null, issue: "invalid_edges" },
  );
});

test("linear pattern parses RU decimals and enforces the server bounds", () => {
  assert.deepEqual(linearPatternSpec({ axis: "x", count: "100", spacing: " 12,5 " }), {
    spec: { axis: "x", count: 100, spacing_mm: 12.5 },
    issue: null,
  });
  assert.deepEqual(linearPatternSpec({ axis: "z", count: "2", spacing: "10000" }), {
    spec: { axis: "z", count: 2, spacing_mm: 10_000 },
    issue: null,
  });
  for (const count of ["", "NaN", "Infinity", "1", "2.5", "101"]) {
    assert.equal(linearPatternSpec({ axis: "x", count, spacing: "1" }).issue, "invalid_count");
  }
  for (const spacing of ["", "NaN", "Infinity", "0", "-1", "10000.1"]) {
    assert.equal(linearPatternSpec({ axis: "z", count: "2", spacing }).issue, "invalid_spacing");
  }
  assert.equal(
    linearPatternSpec({ axis: "q" as never, count: "2", spacing: "1" }).issue,
    "invalid_axis",
  );
});

test("circular pattern parses origin and accepts the inclusive 360 degree default", () => {
  assert.deepEqual(
    circularPatternSpec({
      axis: "z",
      count: "6",
      angle: "360",
      originX: "1,25",
      originY: "-2.5",
      originZ: "0",
    }),
    {
      spec: { axis: "z", count: 6, angle_deg: 360, origin_mm: [1.25, -2.5, 0] },
      issue: null,
    },
  );
  for (const count of ["1", "2,5", "101", "Infinity"]) {
    assert.equal(
      circularPatternSpec({
        axis: "y",
        count,
        angle: "180",
        originX: "0",
        originY: "0",
        originZ: "0",
      }).issue,
      "invalid_count",
    );
  }
  for (const angle of ["", "NaN", "Infinity", "0", "-1", "360.1"]) {
    assert.equal(
      circularPatternSpec({
        axis: "y",
        count: "2",
        angle,
        originX: "0",
        originY: "0",
        originZ: "0",
      }).issue,
      "invalid_angle",
    );
  }
  assert.equal(
    circularPatternSpec({
      axis: "x",
      count: "2",
      angle: "90",
      originX: "not a number",
      originY: "0",
      originZ: "0",
    }).issue,
    "invalid_origin",
  );
});

test("mirror parses RU decimals and fails closed outside the server plane bounds", () => {
  assert.deepEqual(mirrorSpec({ axis: "y", offset: "-10000", keepOriginal: false }), {
    spec: { axis: "y", offset_mm: -10_000, keep_original: false },
    issue: null,
  });
  assert.deepEqual(mirrorSpec({ axis: "z", offset: "10 000", keepOriginal: true }), {
    spec: null,
    issue: "invalid_offset",
  });
  assert.deepEqual(mirrorSpec({ axis: "z", offset: "12,5", keepOriginal: true }), {
    spec: { axis: "z", offset_mm: 12.5, keep_original: true },
    issue: null,
  });
  assert.deepEqual(mirrorSpec({ axis: "x", offset: "10000", keepOriginal: true }), {
    spec: { axis: "x", offset_mm: 10_000, keep_original: true },
    issue: null,
  });
  for (const offset of ["", "NaN", "Infinity", "-10000.1", "10000.1"]) {
    assert.equal(mirrorSpec({ axis: "x", offset, keepOriginal: true }).issue, "invalid_offset");
  }
  assert.equal(
    mirrorSpec({ axis: "x", offset: "0", keepOriginal: "yes" as never }).issue,
    "invalid_keep_original",
  );
});
