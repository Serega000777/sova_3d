import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const capture = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const result = readFileSync(new URL("../app/scan/[id].tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/ScanMaskEditor.tsx", import.meta.url), "utf8");

test("mobile object capture preserves local previews and submits manual mask strokes", () => {
  assert.match(capture, /setCapturedPreviews/);
  assert.match(capture, /mask_corrections: isObjectSubject && maskObject \? maskCorrections : \[\]/);
  assert.match(capture, /delight_object: isObjectSubject && maskObject \? delightObject : false/);
  assert.match(capture, /это не AI-PBR и не восстановление материала/);
  assert.match(result, /delight_luminance_cv_before_mean/);
  assert.match(editor, /"add" \| "remove"/);
  assert.match(editor, /current\.points\.length >= 512/);
  assert.match(editor, /strokes\.length < 64/);
  assert.match(editor, /Ко всем/);
});
