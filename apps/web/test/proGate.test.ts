import assert from "node:assert/strict";
import test from "node:test";

import { isProTierLockedTool, PRO_LOCKED_DETAILS, PRO_LOCKED_TOOLS } from "../src/lib/proGate.ts";

test("hole stays on the Free plan; every other detail operation is Pro-locked", () => {
  assert.equal(isProTierLockedTool("detail", "hole"), false);
  for (const detail of PRO_LOCKED_DETAILS) {
    assert.equal(isProTierLockedTool("detail", detail), true, detail);
  }
});

test("exact CAD and engineering panels are Pro-locked; everything else is free", () => {
  for (const toolId of PRO_LOCKED_TOOLS) {
    assert.equal(isProTierLockedTool(toolId), true, toolId);
  }
  assert.equal(isProTierLockedTool("cad"), true);
  const free = ["chat", "shape", "transform", "scene", "photo", "region", "paint", "size", "measure", "print", "export", "versions", "history", "origin", "licence", "market", "catalog"];
  for (const toolId of free) {
    assert.equal(isProTierLockedTool(toolId), false, toolId);
  }
});

test("a detail tool with no detail kind selected yet is not locked", () => {
  assert.equal(isProTierLockedTool("detail"), false);
});
