import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const viewer = readFileSync(new URL("../src/components/ModelViewer.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("desktop viewport distinguishes mouse touch and pen without making hover destructive", () => {
  assert.match(viewer, /type PointerKind = "mouse" \| "touch" \| "pen"/);
  assert.match(viewer, /hover: preview · contact: orbit · tap: select/);
  assert.match(viewer, /event\.pointerType !== "pen"/);
  assert.match(viewer, /Math\.round\(event\.pressure \* 20\) \* 5/);
});

test("desktop camera shortcuts ignore every editable control", () => {
  assert.match(studio, /Digit0: "iso"/);
  assert.match(studio, /Digit1: "front"/);
  assert.match(studio, /Digit2: "right"/);
  assert.match(studio, /Digit3: "top"/);
  assert.match(studio, /target instanceof HTMLInputElement/);
  assert.match(studio, /target\.isContentEditable/);
});
