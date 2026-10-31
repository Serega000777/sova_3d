import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
  "utf8",
);

test("turntable export uses the version job and its returned asset", () => {
  assert.match(page, /client\.renderVersionTurntableVideo\(activeVersion\.id\)/);
  assert.match(page, /client\.download\(result\.asset_id\)/);
  assert.match(page, /turntableVideo && turntableVideo\.versionId === activeVersion\?\.id/);
});

test("turntable result is an accessible bounded MP4 preview", () => {
  assert.match(page, /<video[\s\S]*?controls[\s\S]*?playsInline[\s\S]*?preload="metadata"/);
  assert.match(page, /<source src=\{turntableVideo\.url\} type="video\/mp4"/);
  assert.match(page, /480×320 · 12 fps/);
  assert.match(page, /Это рендер модели, не AI-видео/);
  assert.match(page, /This renders the model; it is not AI video/);
});
