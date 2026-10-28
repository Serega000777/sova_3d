import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const topBar = readFileSync(new URL("../src/components/TopBar.tsx", import.meta.url), "utf8");
const navIcons = readFileSync(new URL("../src/components/NavIcon.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

test("navigation uses a custom vector icon system without emoji glyphs", () => {
  assert.match(topBar, /<NavIcon name=\{section\.icon\}/);
  assert.match(topBar, /<NavIcon name="plus"/);
  assert.match(navIcons, /viewBox="0 0 24 24"/);
  assert.doesNotMatch(topBar, /⬡|▦|⇄|▤|◇|⌗|▱|☰|✕/);
});

test("motion and materials respect input and accessibility boundaries", () => {
  assert.match(css, /backdrop-filter: saturate\(145%\) blur\(22px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /animation-duration: \.01ms !important/);
  assert.match(css, /--font-ui: "SF Pro Text"/);
});
