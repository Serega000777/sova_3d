import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseDimensionValue, updateDimensionDraft } from "../src/dimension-link.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const size = { x: 120, y: 90, z: 78 };

test("O04 linked dimensions preserve the measured source proportions", () => {
  assert.deepEqual(
    updateDimensionDraft({ x: "120", y: "90", z: "78" }, "x", "60", size, true),
    { x: "60", y: "45", z: "39" },
  );
  assert.deepEqual(
    updateDimensionDraft({ x: "120", y: "90", z: "78" }, "y", "45,5", size, true),
    { x: "60.67", y: "45,5", z: "39.43" },
  );
});

test("O04 independent and incomplete input never invents dimensions", () => {
  assert.deepEqual(
    updateDimensionDraft({ x: "120", y: "90", z: "78" }, "x", "100", size, false),
    { x: "100", y: "90", z: "78" },
  );
  assert.deepEqual(
    updateDimensionDraft({ x: "120", y: "90", z: "78" }, "x", "", size, true),
    { x: "", y: "90", z: "78" },
  );
  assert.equal(parseDimensionValue("12,5"), 12.5);
  assert.equal(parseDimensionValue("0"), null);
});

test("O04 wires the explicit proportions switch to the immutable resize draft", () => {
  assert.match(project, /accessibilityLabel=\{ru \? "Сохранять пропорции размеров"/);
  assert.match(project, /updateDimensionDraft\(current, axis, value, size, dimensionsLinked\)/);
  assert.match(project, /parseDimensionValue\(draft\[key\] \?\? ""\)/);
});
