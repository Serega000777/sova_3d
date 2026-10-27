import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const contract = readFileSync(
  new URL("../../../packages/contracts/src/replacement-part.ts", import.meta.url),
  "utf8",
);

test("reference 71 has a dedicated four-view replacement mode", () => {
  assert.match(project, /Замена детали/);
  assert.match(project, /setGuidedPhotos\(true\)/);
  assert.match(project, /replacement_part:/);
  assert.match(project, /views: replacementViews/);
  assert.match(project, /measurements: measuredReplacement/);
});
test("replacement mode requires a bounded real measurement and states its evidence limit", () => {
  assert.match(contract, /parsed > 0 && parsed <= 10_000/);
  assert.match(project, /Для замены укажите хотя бы один корректный размер/);
  assert.match(project, /REPLACEMENT_DIMENSIONS\.map/);
  assert.match(project, /не доказывают скрытую или утраченную геометрию/);
  assert.match(project, /Недостающие размеры сервис обязан запросить/);
});
