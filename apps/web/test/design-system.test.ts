import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const topBar = readFileSync(new URL("../src/components/TopBar.tsx", import.meta.url), "utf8");
const navIcons = readFileSync(new URL("../src/components/NavIcon.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const plan = readFileSync(new URL("../src/app/plan/page.tsx", import.meta.url), "utf8");
const voice = readFileSync(new URL("../src/components/VoiceButton.tsx", import.meta.url), "utf8");
const proLock = readFileSync(new URL("../src/components/ProLock.tsx", import.meta.url), "utf8");
const market = readFileSync(new URL("../src/app/market/page.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");
const studioIcons = readFileSync(new URL("../src/components/StudioToolIcon.tsx", import.meta.url), "utf8");

test("navigation uses a custom vector icon system without emoji glyphs", () => {
  assert.match(topBar, /<NavIcon name=\{section\.icon\}/);
  assert.match(topBar, /<NavIcon name="plus"/);
  assert.match(navIcons, /viewBox="0 0 24 24"/);
  assert.doesNotMatch(topBar, /⬡|▦|⇄|▤|◇|⌗|▱|☰|✕/);
});

test("studio rail uses custom vector tools and the brand material system", () => {
  assert.match(studio, /<StudioToolIcon name=\{item\.icon\}/);
  assert.match(studio, /<StudioToolIcon name="more"/);
  assert.match(studioIcons, /export type StudioToolIconName/);
  assert.doesNotMatch(studio, /glyph: "(?:⌕|✦|⬡|⌬|◉|⚙|✂|⇪|☰)"/);
  assert.match(css, /box-shadow: inset 3px 0 var\(--accent\)/);
});

test("shared tools use the same vector language instead of emoji", () => {
  assert.match(plan, /<NavIcon name=\{item\.icon\}/);
  assert.match(voice, /<NavIcon name="microphone"/);
  assert.match(proLock, /<NavIcon name="lock"/);
  assert.doesNotMatch(`${plan}${voice}${proLock}${css}`, /🎤|🔒|📍|✋/);
  assert.match(market, /<NavIcon name=\{tab === "all"/);
  assert.match(market, /<NavIcon name="filters"/);
  assert.match(market, /<NavIcon name="cart"/);
});

test("motion and materials respect input and accessibility boundaries", () => {
  assert.match(css, /backdrop-filter: saturate\(145%\) blur\(22px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /animation-duration: \.01ms !important/);
  assert.match(css, /--font-ui: "SF Pro Text"/);
});
