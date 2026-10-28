import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const icons = readFileSync(new URL("../src/AppIcons.tsx", import.meta.url), "utf8");
const plan = readFileSync(new URL("../src/PlanAnnotator.tsx", import.meta.url), "utf8");
const voice = readFileSync(new URL("../src/VoiceButton.tsx", import.meta.url), "utf8");

test("mobile editing tools and voice use the custom SVG icon set", () => {
  assert.match(icons, /export function MicrophoneIcon/);
  assert.match(icons, /export function PencilIcon/);
  assert.match(plan, /<ToolIcon tool=\{item\.id\}/);
  assert.match(voice, /<MicrophoneIcon/);
  assert.doesNotMatch(`${plan}${voice}`, /🎤|📍|✋/);
});
