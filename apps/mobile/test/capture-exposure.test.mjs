import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  clampExposureStep,
  exposureLabel,
  exposureValue,
} from "../src/capture-exposure.ts";

const captureScreen = readFileSync(new URL("../app/scan/index.tsx", import.meta.url), "utf8");
const tracker = readFileSync(new URL("../src/scan.ts", import.meta.url), "utf8");
const nativePatch = readFileSync(
  new URL("../../../patches/expo-camera@57.0.6.patch", import.meta.url),
  "utf8",
);

test("manual exposure is finite, bounded and has a neutral reset", () => {
  assert.equal(clampExposureStep(Number.NaN), 0);
  assert.equal(clampExposureStep(-99), -4);
  assert.equal(clampExposureStep(99), 4);
  assert.equal(exposureValue(-4), -1);
  assert.equal(exposureValue(0), 0);
  assert.equal(exposureValue(4), 1);
  assert.equal(exposureLabel(0), "Авто · 0%");
  assert.equal(exposureLabel(2), "+50%");
});

test("object capture applies exposure to preview and persists it with each frame", () => {
  assert.match(captureScreen, /manualExposureAvailable[\s\S]*exposure: isObjectSubject \? exposureValue\(exposureStep\) : 0/);
  assert.match(captureScreen, /exposureCompensation: exposureValue\(exposureStep\)/);
  assert.match(captureScreen, /setExposureStep\(0\)/);
  assert.match(captureScreen, /Expo Go оставляет нейтральную автоэкспозицию/);
  assert.match(tracker, /exposure_compensation:/);
});

test("native patch maps the normalized value through both platform camera APIs", () => {
  assert.match(nativePatch, /device\.minExposureTargetBias/);
  assert.match(nativePatch, /device\.maxExposureTargetBias/);
  assert.match(nativePatch, /device\.setExposureTargetBias/);
  assert.match(nativePatch, /state\.exposureCompensationRange/);
  assert.match(nativePatch, /setExposureCompensationIndex/);
  assert.match(nativePatch, /exposure\?: number/);
});
