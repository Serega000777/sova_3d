import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { localEditPreviewVersion } from "../src/local-edit-preview.ts";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("mobile local AI edits stay draft until an explicit decision", () => {
  assert.match(project, /const previewRequested = Boolean\(region\)/);
  assert.match(project, /preview: previewRequested/);
  assert.match(project, /client\.compareVersion\(version\.id\)/);
  assert.match(project, /client\.acceptVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /client\.discardVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /Локальная правка ещё не применена/);
});

test("local edit viewport switches only between the immutable before and draft versions", () => {
  const before = { id: "version-before" };
  const after = { id: "version-draft" };

  assert.equal(localEditPreviewVersion("before", before, after), before);
  assert.equal(localEditPreviewVersion("after", before, after), after);
  assert.equal(localEditPreviewVersion("before", null, after), after);
  assert.match(project, /setLocalEditPreviewSide\(side\)/);
  assert.match(project, /localEditPreview\.beforeVersion/);
  assert.match(project, /Показать 3D до/);
  assert.match(project, /Показать 3D после/);
});

test("clarified region commands cannot bypass the preview decision", () => {
  const replyStart = project.indexOf("async function reply()");
  const replyEnd = project.indexOf("async function resize()", replyStart);
  const reply = project.slice(replyStart, replyEnd);
  assert.match(reply, /showLocalEditPreview\(job\)/);
  assert.match(reply, /setRegion\(null\)/);
  assert.ok(reply.indexOf("showLocalEditPreview(job)") < reply.indexOf("setRegion(null)"));
});
