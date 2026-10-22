import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Sova centre continues the real most recently updated project without invented progress", () => {
  const source = readFileSync(new URL("../app/(tabs)/index.tsx", import.meta.url), "utf8");

  assert.match(source, /libraryView\(projects, \{ query: "", filter: "all", sort: "updated" \}\)/);
  assert.match(source, /const continueProject = recentProjects\[0\] \?\? null/);
  assert.match(source, /Продолжить работу/);
  assert.match(source, /href=\{`\/project\/\$\{continueProject\.id\}`\}/);
  assert.match(source, /continueProject\.head_version_id \? "Последняя сохранённая модель" : "Черновик без модели"/);
  assert.doesNotMatch(source, /82%|процент готовности|готово на/);
});
