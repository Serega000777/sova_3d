import assert from "node:assert/strict";
import test from "node:test";

import { buildMobileSketchRelations } from "../src/exact-sketch-relations.ts";

const lines = Array.from({ length: 4 }, () => ({ kind: "line" }));

test("mobile sketch relations map point and edge picks to canonical constraints", () => {
  assert.deepEqual(buildMobileSketchRelations([
    { kind: "coincident", first: "0", second: "2" },
    { kind: "equal_length", first: "0", second: "2" },
    { kind: "parallel", first: "0", second: "2" },
    { kind: "perpendicular", first: "0", second: "1" },
  ], 4, lines), {
    constraints: [
      { kind: "coincident", first: 0, second: 2 },
      { kind: "equal_length", first_start: 0, first_end: 1, second_start: 2, second_end: 3 },
      { kind: "parallel", first_start: 0, first_end: 1, second_start: 2, second_end: 3 },
      { kind: "perpendicular", first_start: 0, first_end: 1, second_start: 1, second_end: 2 },
    ],
    issueIndex: null,
  });
});

test("mobile sketch relations reject bad indices, duplicate relations, and curved edges", () => {
  assert.equal(buildMobileSketchRelations([
    { kind: "parallel", first: "0", second: "4" },
  ], 4, lines).issueIndex, 0);
  assert.equal(buildMobileSketchRelations([
    { kind: "coincident", first: "1", second: "1" },
  ], 4, lines).issueIndex, 0);
  assert.equal(buildMobileSketchRelations([
    { kind: "equal_length", first: "0", second: "2" },
    { kind: "equal_length", first: "2", second: "0" },
  ], 4, lines).issueIndex, 1);
  assert.equal(buildMobileSketchRelations([
    { kind: "perpendicular", first: "0", second: "1" },
  ], 4, [{ kind: "line" }, { kind: "arc", center_mm: [10, 10] }, { kind: "line" }, { kind: "line" }]).issueIndex, 0);
});

test("mobile sketch relations keep their own bounded budget", () => {
  const tooMany = Array.from({ length: 17 }, (_, index) => ({
    kind: "coincident",
    first: String(index % 3),
    second: String((index + 1) % 3),
  }));
  assert.equal(buildMobileSketchRelations(tooMany, 4, lines).issueIndex, 0);
});
