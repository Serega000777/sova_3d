import assert from "node:assert/strict";
import test from "node:test";

import { exactHoleSpec, shellSpec } from "../src/exact-detail.ts";

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
  assert.deepEqual(shellSpec({ thickness: " 2,5 " }), {
    spec: { thickness_mm: 2.5 },
    issue: null,
  });
  assert.deepEqual(shellSpec({ thickness: "10000" }), {
    spec: { thickness_mm: 10_000 },
    issue: null,
  });
});

test("exact shell fails closed for malformed or out-of-range thickness", () => {
  for (const thickness of ["", " ", "not a number", "NaN", "Infinity", "-Infinity", "0", "-1", "10000.1"]) {
    assert.deepEqual(shellSpec({ thickness }), {
      spec: null,
      issue: "invalid_thickness",
    });
  }
});
