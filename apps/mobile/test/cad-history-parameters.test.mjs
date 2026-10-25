import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sheet = readFileSync(new URL("../src/CadHistorySheet.tsx", import.meta.url), "utf8");

test("mobile exact CAD history edits only shared kernel-approved parameters", () => {
  assert.match(sheet, /editableOperationParameters\(entries\)/);
  assert.match(sheet, /operationParameterValue\(parameter, input\)/);
  assert.match(sheet, /setParameterOperation\(parameter, value\)/);
  assert.match(sheet, /client\.createEdit\(versionId/);
  assert.match(sheet, /await onJob\(accepted\.job_id\)/);
  assert.match(sheet, /disabled=\{disabled \|\| !entry\.enabled/);
});
