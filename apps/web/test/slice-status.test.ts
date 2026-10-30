import assert from "node:assert/strict";
import test from "node:test";

import {
  composeMaterialSummary,
  describeMaterialExecution,
} from "../src/lib/slice-status.ts";

test("completed multi-material stats report exact physical transitions and purge facts", () => {
  assert.equal(
    describeMaterialExecution({
      planned_tool_change_layers: 4,
      planned_tool_changes: 8,
      planned_purge_volume_mm3: 600.5,
      purge_tower_reserved: true,
      purge_tower_width_mm: 24.5,
    }),
    "физические переходы: 8 на 4 слоях · purge 600.5 мм³ · purge-башня зарезервирована, ширина 24.5 мм",
  );
});

test("zero transition plan is distinct from a disabled capability", () => {
  assert.equal(
    describeMaterialExecution({
      planned_tool_change_layers: 0,
      planned_tool_changes: 0,
      planned_purge_volume_mm3: 0,
      purge_tower_reserved: false,
      purge_tower_width_mm: 0,
    }),
    "физических переходов в этом slice нет",
  );
});

test("legacy results without transition fields make no execution claim", () => {
  assert.equal(describeMaterialExecution({}), null);
  assert.equal(describeMaterialExecution({ planned_tool_changes: 2 }), null);
});

test("physical execution is independent of absent or zero assigned-region metadata", () => {
  for (const material_assigned_regions of [undefined, 0]) {
    const summary = composeMaterialSummary({
      material_assigned_regions,
      planned_tool_change_layers: 3,
      planned_tool_changes: 6,
      planned_purge_volume_mm3: 240,
      purge_tower_reserved: true,
      purge_tower_width_mm: 20,
    });

    assert.equal(summary.assignment, null);
    assert.equal(
      summary.execution,
      "физические переходы: 6 на 3 слоях · purge 240 мм³ · purge-башня зарезервирована, ширина 20 мм",
    );
  }
});

test("summary keeps old results safe and assignment separately conditional", () => {
  assert.deepEqual(composeMaterialSummary({}), { assignment: null, execution: null });
  assert.deepEqual(composeMaterialSummary({ material_assigned_regions: 2 }), {
    assignment: "материал назначен 2 областям",
    execution: null,
  });
});
