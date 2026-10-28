import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  defaultSizeFamilyDraft,
  parseSizeFamilyDraft,
  sizeFamilyOutputMatches,
} from "../src/size-family.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 81 builds three exact drafts from one immutable source", () => {
  assert.match(project, /const source = active/);
  assert.match(project, /parseSizeFamilyDraft\(sizeFamilyDraft\)/);
  assert.match(project, /client\.createEdit\(source\.id/);
  assert.match(project, /type: "set_dimensions"/);
  assert.match(project, /width_mm: preset\.widthMm/);
  assert.match(project, /depth_mm: preset\.depthMm/);
  assert.match(project, /height_mm: preset\.heightMm/);
  assert.match(project, /preview: true/);
});

test("the default table preserves depth and height but every S/M/L dimension is editable", () => {
  const draft = defaultSizeFamilyDraft({ x: 80, y: 40, z: 20 });
  assert.deepEqual(draft, {
    S: { width: "60", depth: "40", height: "20" },
    M: { width: "80", depth: "40", height: "20" },
    L: { width: "100", depth: "40", height: "20" },
  });
  draft.S.depth = "35,5";
  draft.M.height = "25";
  draft.L.width = "120.25";
  assert.deepEqual(parseSizeFamilyDraft(draft), [
    { label: "S", widthMm: 60, depthMm: 35.5, heightMm: 20 },
    { label: "M", widthMm: 80, depthMm: 40, heightMm: 25 },
    { label: "L", widthMm: 120.25, depthMm: 40, heightMm: 20 },
  ]);
  assert.match(project, /Таблица размеров S M L/);
  assert.match(project, /updateSizeFamilyDraft\(label, dimension, value\)/);
});

test("the table fails closed for incomplete, non-finite, non-positive and oversized values", () => {
  const invalid = ["", "NaN", "Infinity", "0", "-1", "10000.001"];
  for (const value of invalid) {
    const draft = defaultSizeFamilyDraft({ x: 80, y: 40, z: 20 });
    draft.M.depth = value;
    assert.equal(parseSizeFamilyDraft(draft), null, value);
  }
});

test("the family fails closed and keeps exactly one explicit choice", () => {
  assert.match(project, /if \(completed\.length !== presets\.length\)/);
  assert.match(project, /неполное семейство удалено/);
  assert.match(project, /if \(chosen\) await client\.acceptVersion\(chosen\.id\)/);
  assert.match(project, /item\.version\.id !== chosen\?\.id/);
  assert.match(project, /client\.discardVersion\(item\.version\.id\)/);
  assert.match(project, /decideSizeFamily\(null\)/);
});

test("every measured draft must match its requested S M or L row", () => {
  const preset = { label: "M", widthMm: 80, depthMm: 40, heightMm: 20 };
  assert.equal(sizeFamilyOutputMatches([80, 40, 20], preset), true);
  assert.equal(sizeFamilyOutputMatches([80.009, 39.991, 20], preset), true);
  assert.equal(sizeFamilyOutputMatches([80.02, 40, 20], preset), false);
  assert.equal(sizeFamilyOutputMatches([80, 40], preset), false);
  assert.equal(sizeFamilyOutputMatches([80, Number.NaN, 20], preset), false);
  assert.match(project, /sizeFamilyOutputMatches\(measured, preset\)/);
});
