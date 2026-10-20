import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/ExactShellSheet.tsx", import.meta.url), "utf8");

test("mobile exact shell sends the chosen axis face through the typed helper", () => {
  assert.match(source, /shellSpec\(\{ thickness, openFace, axis, sign \}\)/);
  assert.match(source, /open_face/);
  assert.match(source, /opened\.axis/);
  assert.match(source, /opened\.sign/);
});

test("mobile exact shell keeps closed and open-face modes explicit", () => {
  assert.match(source, /setOpenFace\(false\)/);
  assert.match(source, /setOpenFace\(true\)/);
  assert.match(source, /\["x", "y", "z"\]/);
  assert.match(source, /\["\+", "-"\]/);
});
