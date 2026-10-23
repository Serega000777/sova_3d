import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { parseDimensionedDrawingHoles } from "../src/dimensioned-drawing.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const client = readFileSync(new URL("../../../packages/contracts/src/client.ts", import.meta.url), "utf8");

test("dimension rows preserve signed coordinates and explicit diameter symbols", () => {
  assert.deepEqual(parseDimensionedDrawingHoles("-25, 0, Ø10\n25; 0; ⌀8"), [
    { x_mm: -25, y_mm: 0, diameter_mm: 10 },
    { x_mm: 25, y_mm: 0, diameter_mm: 8 },
  ]);
  assert.equal(parseDimensionedDrawingHoles("0, 0"), null);
  assert.equal(parseDimensionedDrawingHoles("0, 0, Øx"), null);
});

test("dimensioned-part project requires a calibrated source before exact tracing", () => {
  assert.match(project, /projectGoal\?\.id === "dimensioned_part"/);
  assert.match(project, /projectReference\.known_mm <= 0/);
  assert.match(project, /client\.createDimensionedDrawing\(id, trace\)/);
  assert.match(project, /исходный калиброванный чертёж сохранён в provenance/);
  assert.match(client, /createDimensionedDrawing\([\s\S]*?DimensionedDrawingBody/);
});
