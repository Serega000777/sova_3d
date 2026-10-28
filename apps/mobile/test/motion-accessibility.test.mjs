import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const motion = readFileSync(new URL("../src/MotionPressable.tsx", import.meta.url), "utf8");
const projects = readFileSync(new URL("../app/(tabs)/projects.tsx", import.meta.url), "utf8");
const market = readFileSync(new URL("../app/(tabs)/market.tsx", import.meta.url), "utf8");

test("primary mobile surfaces use short spring feedback with reduced-motion support", () => {
  assert.match(motion, /AccessibilityInfo\.isReduceMotionEnabled/);
  assert.match(motion, /reduceMotionChanged/);
  assert.match(motion, /Animated\.spring/);
  assert.match(motion, /speed: 36/);
  assert.match(projects, /<MotionPressable/);
  assert.match(market, /<MotionPressable/);
});
