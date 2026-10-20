import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/Onboarding.tsx", import.meta.url), "utf8");

test("the refreshed onboarding is versioned and uses a tappable segmented mission progress", () => {
  assert.match(source, /sova\.onboarded\.v6/);
  assert.match(source, /style=\{s\.progressSegment\}/);
  assert.match(source, /index <= step && s\.progressFillActive/);
  assert.match(source, /onPress=\{\(\) => goTo\(index\)\}/);
});

test("the story names the four reference use cases without promising unsupported quality", () => {
  assert.match(source, /Игровые персонажи/);
  assert.match(source, /Аксессуары и декор/);
  assert.match(source, /Готово к 3D-печати/);
  assert.match(source, /Детальные PBR-материалы/);
  assert.match(source, /game-ready GLB/);
  assert.match(source, /assets\/scenarios\/game_character\.png/);
  assert.match(source, /assets\/scenarios\/printable_object\.png/);
});

test("early onboarding slides use one explicit continue action and preserve back navigation", () => {
  assert.match(source, /accessibilityLabel=\{ru \? "Продолжить" : "Continue"\}/);
  assert.match(source, /onPress=\{next\}/);
  assert.match(source, /onPress=\{\(\) => goTo\(step - 1\)\}/);
});
