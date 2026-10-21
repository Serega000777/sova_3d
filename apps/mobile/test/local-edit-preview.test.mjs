import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("mobile local AI edits stay draft until an explicit decision", () => {
  assert.match(project, /const previewRequested = Boolean\(region\)/);
  assert.match(project, /preview: previewRequested/);
  assert.match(project, /client\.compareVersion\(version\.id\)/);
  assert.match(project, /client\.acceptVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /client\.discardVersion\(localEditPreview\.version\.id\)/);
  assert.match(project, /Локальная правка ещё не применена/);
});

test("clarified region commands cannot bypass the preview decision", () => {
  const replyStart = project.indexOf("async function reply()");
  const replyEnd = project.indexOf("async function resize()", replyStart);
  const reply = project.slice(replyStart, replyEnd);
  assert.match(reply, /showLocalEditPreview\(job\)/);
  assert.match(reply, /setRegion\(null\)/);
  assert.ok(reply.indexOf("showLocalEditPreview(job)") < reply.indexOf("setRegion(null)"));
});
