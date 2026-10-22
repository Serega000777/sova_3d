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
  assert.match(source, /client\.repairModel\(activeVersion\.id, step \? \{ steps: \[step\] \}/);
  assert.match(source, /defect\.repairStep === "fragments" \? null/);
  assert.match(source, /Нужна ручная правка сетки/);
});
