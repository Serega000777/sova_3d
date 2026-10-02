import assert from "node:assert/strict";
import test from "node:test";

import { isProfiLockedTool, PROFI_LOCKED_DETAILS, PROFI_LOCKED_TOOLS } from "../src/lib/profiGate.ts";

test("hole stays on the free Pro plan; every other detail operation is Profi-locked", () => {
  assert.equal(isProfiLockedTool("detail", "hole"), false);
  for (const detail of PROFI_LOCKED_DETAILS) {
    assert.equal(isProfiLockedTool("detail", detail), true, detail);
  }
});

test("reverse/engineer/fit/parts panels are Profi-locked; everything else is free", () => {
  for (const toolId of PROFI_LOCKED_TOOLS) {
    assert.equal(isProfiLockedTool(toolId), true, toolId);
  }
  const free = ["chat", "shape", "transform", "scene", "photo", "region", "paint", "size", "measure", "print", "export", "versions", "history", "origin", "licence", "market", "catalog"];
  for (const toolId of free) {
    assert.equal(isProfiLockedTool(toolId), false, toolId);
  }
});

test("a detail tool with no detail kind selected yet is not locked", () => {
  assert.equal(isProfiLockedTool("detail"), false);
});
