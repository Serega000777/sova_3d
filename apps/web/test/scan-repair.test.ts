import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("web scan repair exposes measured defect categories and selective repair", () => {
  for (const label of [
    "Большое отверстие",
    "Плавающий фрагмент",
    "Разрыв поверхности",
    "Шумовой фрагмент",
    "Ошибка нормалей",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /client\.repairModel\(\s*activeVersion\.id,\s*step \? \{ steps: \[step\]/);
  assert.match(source, /defect_ids: defectIds/);
  assert.match(source, /repair-defect-\$\{defect\.id\}/);
  assert.match(source, /selectedRepairDefectIds\.length > 0 && !defectIds\?\.length/);
  assert.match(source, /Select a floating fragment to remove/);
  assert.match(source, /defect\.repairStep === "fragments" \? null/);
  assert.match(source, /Нужна ручная правка сетки/);
});
