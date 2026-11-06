import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { localEditPreviewVersion } from "../src/local-edit-preview.ts";

const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

const sendCommand = studio.slice(
  studio.indexOf("async function sendCommand"),
  studio.indexOf("async function applyCommandProposal"),
);
const sendAnswer = studio.slice(
  studio.indexOf("async function sendAnswer"),
  studio.indexOf("async function analyze"),
);
const showPreviewIfDraft = studio.slice(
  studio.indexOf("async function showPreviewIfDraft"),
  studio.indexOf("async function decidePreview"),
);
const decidePreview = studio.slice(
  studio.indexOf("async function decidePreview"),
  studio.indexOf("/** The answer lives inside the command form"),
);

test("reference 76 region commands stay a draft until an explicit web decision", () => {
  assert.match(sendCommand, /preview: previewMode/);
  assert.match(sendCommand, /region,/);
  assert.match(showPreviewIfDraft, /client\.compareVersion\(version\.id\)/);
  assert.match(decidePreview, /client\.acceptVersion\(preview\.version\.id\)/);
  assert.match(decidePreview, /client\.discardVersion\(preview\.version\.id\)/);
  assert.match(studio, /Команда и область локальной правки/);
  assert.match(studio, /regionSize\(preview\.region\)/);
});

test("the decision card is bound to the exact submitted command and region for the initial job", () => {
  assert.match(sendCommand, /afterAiJob\(accepted\.ai_request_id, job, \{ command: text, region \}\)/);
});

test("clarified region commands keep the same binding instead of bypassing the decision", () => {
  assert.match(sendAnswer, /afterAiJob\(pending\.id, job, \{ command: pending\.prompt, region \}\)/);
});

test("the viewport switches only between the exact immutable source and the exact draft", () => {
  const before = { id: "version-before" };
  const after = { id: "version-draft" };

  assert.equal(localEditPreviewVersion("before", before, after), before);
  assert.equal(localEditPreviewVersion("after", before, after), after);
  // A missing source fails closed to the draft rather than showing unrelated geometry.
  assert.equal(localEditPreviewVersion("before", null, after), after);
  assert.equal(localEditPreviewVersion("before", undefined, after), after);
  assert.match(studio, /setPreviewSide\(side\)/);
  assert.match(studio, /preview\.beforeVersion/);
  assert.match(studio, /Показать 3D до/);
  assert.match(studio, /Показать 3D после/);
  assert.match(showPreviewIfDraft, /localEditPreviewVersion\("after", beforeVersion, version\)/);
});
