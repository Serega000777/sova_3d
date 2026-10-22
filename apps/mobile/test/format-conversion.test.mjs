import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 89 exposes the server-supported FBX conversion path", () => {
  assert.match(source, /exportModel\(format: "stl" \| "3mf" \| "glb" \| "fbx"\)/);
  assert.match(source, /format: "fbx", title: "FBX"/);
  assert.match(source, /client\.exportModel\(active\.id, \{/);
  assert.match(source, /const download = await client\.download\(result\.asset_id\)/);
});

test("mobile conversion copy does not invent unit or axis controls", () => {
  assert.match(source, /Геометрия хранится[\s\S]*в миллиметрах/);
  assert.match(source, /ручная смена масштаба и осей при экспорте пока недоступна/);
  assert.doesNotMatch(source, /format: "obj"/);
});
