import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(new URL("../src/components/OperationStackPanel.tsx", import.meta.url), "utf8");
const project = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("web feature tree sends validated parameter edits through immutable exact CAD replay", () => {
  assert.match(panel, /editableOperationParameters\(entries\)/);
  assert.match(panel, /operationParameterValue\(parameter, input\)/);
  assert.match(panel, /onEditParameter\(parameter, parsed\)/);
  assert.match(project, /setParameterOperation\(parameter, value\)/);
  assert.match(project, /client\.createEdit\(activeVersion\.id/);
  assert.match(project, /job\.status !== "succeeded"/);
  assert.match(project, /onEditParameter=\{editOperationParameter\}/);
});
