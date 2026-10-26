import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const upload = readFileSync(new URL("../src/scan.ts", import.meta.url), "utf8");
const contract = readFileSync(
  new URL("../../../packages/contracts/src/broken-part-capture.ts", import.meta.url),
  "utf8",
);

test("reference 72 records each required broken-part series on the real frames", () => {
  assert.match(screen, /broken_part_sections_v1/);
  assert.match(screen, /brokenPartSection/);
  assert.match(upload, /broken_part_section: context\.brokenPartSection/);
  assert.match(contract, /id: "whole"/);
  assert.match(contract, /id: "fracture"/);
  assert.match(contract, /id: "interior"/);
});

test("broken-part reconstruction stays blocked until every series is covered", () => {
  assert.match(screen, /isBrokenPart && uncoveredBrokenPart\.length > 0/);
  assert.match(screen, /Перед сборкой снимите весь объект, границу слома/);
  assert.match(screen, /приложение не определяет место слома автоматически/);
  assert.match(screen, /Это покрытие кадров, не распознавание повреждения/);
});
