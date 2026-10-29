import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");

test("slicer exposes explicit adhesion modes and sends the selected real settings", () => {
  assert.match(page, /Сцепление с печатным столом/);
  assert.match(page, /\["auto", "Авто"\]/);
  assert.match(page, /\["skirt", "Юбка"\]/);
  assert.match(page, /\["brim", "Кайма"\]/);
  assert.match(page, /\["none", "Без неё"\]/);
  assert.match(page, /adhesion_mode: adhesionMode/);
  assert.match(page, /brim_width_mm: brimWidthMm/);
  assert.match(page, /disabled=\{adhesionMode !== "brim"\}/);
  assert.match(page, /ручной выбор всегда имеет\s+приоритет/);
});
