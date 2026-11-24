import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const planPage = readFileSync(new URL("../src/app/plan/page.tsx", import.meta.url), "utf8");

test("web places and auto-furnishes on the selected measured floor", () => {
  assert.match(planPage, /z_mm: activeFloor\?\.elevation_mm \?\? 0/);
  assert.match(planPage, /auto_furnish: typedLayout && autoFurnish/);
  assert.doesNotMatch(planPage, /floor-elevation-aware furniture placement is a separate increment/i);
  assert.doesNotMatch(planPage, /furnitureDropDisabled=.*multiFloor/);
});

test("one room program can be applied sequentially to every immutable floor", () => {
  assert.match(planPage, /const \[layoutAllFloors, setLayoutAllFloors\] = useState\(false\)/);
  assert.match(planPage, /floorLevels\.map\(\(level\) => level\.index\)\.sort/);
  assert.match(planPage, /for \(const floorIndex of targetFloorIndexes\)/);
  assert.match(planPage, /base_version_id: currentVersionId/);
  assert.match(planPage, /currentVersionId = result\.version_id/);
  assert.match(planPage, /currentVersionId = jobResult\.version_id/);
  assert.match(planPage, /level\.index === floorIndex \? \{ \.\.\.level, plan: parsed \} : level/);
  assert.match(planPage, /completedFloors > 0 && layoutAllFloors/);
  assert.match(planPage, /уже созданные immutable-версии остаются сохранены/);
  assert.match(planPage, /getCrossFloorAlignment\(projectId\)/);
});

test("cross-floor report stays geometric and labels untyped wet zones honestly", () => {
  assert.match(planPage, /Межэтажная геометрия/);
  assert.match(planPage, /Мокрые зоны не проверены: нужны типизированные комнаты/);
  assert.match(planPage, /не расчёт несущих стен, балок, нагрузок, стояков или трасс труб/);
  assert.match(planPage, /pair\.partitions\.aligned_lower_count/);
  assert.match(planPage, /pair\.wet_zones\.overlapping_upper_count/);
});

test("web plan overlay shows only furniture from the active floor elevation", () => {
  assert.match(
    planPage,
    /node\.world_transform\[2\]\?\.\[3\].*activeFloor\?\.elevation_mm/s,
  );
  assert.match(planPage, /\[client, baseVersionId, activeFloor\?\.elevation_mm\]/);
});
