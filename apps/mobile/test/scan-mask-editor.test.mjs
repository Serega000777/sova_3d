import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const capture = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/ScanMaskEditor.tsx", import.meta.url), "utf8");

test("mobile object capture preserves local previews and submits manual mask strokes", () => {
  assert.match(capture, /setCapturedPreviews/);
  assert.match(capture, /mask_corrections: isObjectSubject && maskObject \? maskCorrections : \[\]/);
  assert.match(editor, /"add" \| "remove"/);
  assert.match(editor, /current\.points\.length >= 512/);
  assert.match(editor, /strokes\.length < 64/);
  assert.match(editor, /Ко всем/);
});
