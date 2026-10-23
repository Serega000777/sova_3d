import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/scanner/[id]/page.tsx", import.meta.url), "utf8");
const editor = readFileSync(new URL("../src/components/ScanMaskEditor.tsx", import.meta.url), "utf8");

test("web scan mask editor submits bounded add/remove strokes to reconstruction", () => {
  assert.match(page, /mask_corrections: maskObject \? maskCorrections : \[\]/);
  assert.match(editor, /"add" \| "remove"/);
  assert.match(editor, /points\.length >= 512/);
  assert.match(editor, /strokes\.length >= 64/);
  assert.match(editor, /Применить эти штрихи ко всем/);
  assert.match(editor, /До · исходный кадр/);
  assert.match(editor, /После · правки поверх авто-маски/);
});
