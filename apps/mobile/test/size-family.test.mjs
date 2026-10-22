import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 81 builds three exact drafts from one immutable source", () => {
  assert.match(project, /const source = active/);
  assert.match(project, /label: "S" as const, factor: 0\.75/);
  assert.match(project, /label: "M" as const, factor: 1/);
  assert.match(project, /label: "L" as const, factor: 1\.25/);
  assert.match(project, /client\.createEdit\(source\.id/);
  assert.match(project, /type: "set_dimensions"/);
  assert.match(project, /depth_mm: Math\.round\(size\.y/);
  assert.match(project, /height_mm: Math\.round\(size\.z/);
  assert.match(project, /preview: true/);
});

test("the family fails closed and keeps exactly one explicit choice", () => {
  assert.match(project, /if \(completed\.length !== presets\.length\)/);
  assert.match(project, /неполное семейство удалено/);
  assert.match(project, /if \(chosen\) await client\.acceptVersion\(chosen\.id\)/);
  assert.match(project, /item\.version\.id !== chosen\?\.id/);
  assert.match(project, /client\.discardVersion\(item\.version\.id\)/);
  assert.match(project, /decideSizeFamily\(null\)/);
});
