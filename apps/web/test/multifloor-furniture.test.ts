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

test("web plan overlay shows only furniture from the active floor elevation", () => {
  assert.match(
    planPage,
    /node\.world_transform\[2\]\?\.\[3\].*activeFloor\?\.elevation_mm/s,
  );
  assert.match(planPage, /\[client, baseVersionId, activeFloor\?\.elevation_mm\]/);
});
