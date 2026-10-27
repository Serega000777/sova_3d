import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("mobile reloads stored engineering reports for the active immutable version", () => {
  const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
  const card = readFileSync(new URL("../src/EngineerCard.tsx", import.meta.url), "utf8");
  assert.match(project, /listEngineeringReports\(activeId\)/);
  assert.match(project, /history=\{engineeringHistory\}/);
  assert.match(card, /История инженерных проверок/);
  assert.match(card, /не подтверждение допустимой нагрузки/);
  assert.match(card, /history\.slice\(0, 5\)/);
  assert.match(card, /answer=\{answer\}[\s\S]*onApplyFix=\{onApplyFix\}/);
});
