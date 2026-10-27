import assert from "node:assert/strict";
import test from "node:test";

import {
  REPLACEMENT_DIMENSIONS,
  parseReplacementKnownMm,
  parseReplacementMeasurements,
  replacementDimensionLabel,
} from "../src/replacement-part.ts";

test("replacement measurements accept only bounded positive millimetres", () => {
  assert.equal(parseReplacementKnownMm("120"), 120);
  assert.equal(parseReplacementKnownMm("25,5"), 25.5);
  for (const value of ["", "0", "-1", "10001", "NaN", "Infinity"]) {
    assert.equal(parseReplacementKnownMm(value), null);
  }
});

test("replacement measurements keep every supplied dimension and require at least one", () => {
  assert.deepEqual(
    parseReplacementMeasurements({ length: "120", width: "25,5", height: "95" }),
    { length: 120, width: 25.5, height: 95 },
  );
  assert.deepEqual(parseReplacementMeasurements({ hole_diameter: "8" }), { hole_diameter: 8 });
  assert.equal(parseReplacementMeasurements({}), null);
  assert.equal(parseReplacementMeasurements({ length: "120", width: "0" }), null);
});

test("replacement dimension choices are stable and localized", () => {
  assert.deepEqual(REPLACEMENT_DIMENSIONS, ["length", "width", "height", "hole_diameter"]);
  assert.equal(replacementDimensionLabel("hole_diameter", "ru"), "Ø отверстия");
  assert.equal(replacementDimensionLabel("length", "en"), "Length");
});
