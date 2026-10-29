import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/slicer/page.tsx", import.meta.url), "utf8");

test("slicer exposes explicit adhesion modes and sends the selected real settings", () => {
  assert.match(page, /Сцепление с печатным столом/);
  assert.match(page, /\["auto", "Авто"\]/);
  assert.match(page, /\["skirt", "Юбка"\]/);
  assert.match(page, /\["brim", "Кайма"\]/);
  assert.match(page, /\["mouse_ears", "Ушки"\]/);
  assert.match(page, /\["raft", "Рафт"\]/);
  assert.match(page, /\["none", "Без неё"\]/);
  assert.match(page, /adhesion_mode: adhesionMode/);
  assert.match(page, /brim_width_mm: brimWidthMm/);
  assert.match(page, /mouse_ear_diameter_mm: mouseEarDiameterMm/);
  assert.match(page, /mouse_ear_points_mm:/);
  assert.match(page, /Расставить на модели/);
  assert.match(page, /onViewportPick=/);
  assert.match(page, /markers=\{mouseEarPoints\.map/);
  assert.match(page, /process_modifiers: processModifiers/);
  assert.match(page, /print_speed_pct: processSpeedPct/);
  assert.match(page, /infill_pattern:/);
  assert.match(page, /wall_count:/);
  assert.match(page, /Локальный рисунок заполнения/);
  assert.match(page, /Локальная скорость печати/);
  assert.match(page, /Локальная плотность/);
  assert.match(page, /Локальное число стенок/);
  assert.match(page, /selection\.region\.axis !== "z"/);
  assert.match(page, /raft_margin_mm: raftMarginMm/);
  assert.match(page, /disabled=\{adhesionMode !== "brim"\}/);
  assert.match(page, /disabled=\{adhesionMode !== "mouse_ears"\}/);
  assert.match(page, /disabled=\{adhesionMode !== "raft"\}/);
  assert.match(page, /ручной выбор всегда имеет\s+приоритет/);
});
