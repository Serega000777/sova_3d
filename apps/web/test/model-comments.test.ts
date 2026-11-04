import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(new URL("../src/components/ModelCommentsPanel.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 63 web discussion stays bound to the exact immutable version and model point", () => {
  assert.match(panel, /client\.listModelComments\(versionId\)/);
  assert.match(panel, /client\.createModelComment\(versionId, text, pendingPoint, mentions\)/);
  assert.match(panel, /data-version-id=\{versionId/);
  assert.match(studio, /modelCommentPicking/);
  assert.match(studio, /setModelCommentPoint\(point\)/);
  assert.match(studio, /comment\.version_id === activeVersion\?\.id/);
  assert.match(studio, /comment\.parent_comment_id === null/);
});

test("reference 63 web discussion uses canonical threads, mentions, roles, and CAS", () => {
  assert.match(panel, /client\.listWorkspaceMembers\(workspaceId\)/);
  assert.match(panel, /client\.createModelCommentReply\(root\.id, text, replyMentions\)/);
  assert.match(panel, /saved\.parent_comment_id !== root\.id/);
  assert.match(panel, /client\.updateModelComment\(/);
  assert.match(panel, /comment\.revision/);
  assert.match(panel, /reason instanceof ApiError && reason\.status === 409/);
  assert.match(panel, /canEdit \?/);
});

test("reply comments do not create duplicate viewport markers", () => {
  assert.match(studio, /parent_comment_id === null/);
  assert.doesNotMatch(studio, /modelComments\.map\(\(comment\) => \(\{/);
});

test("web comment photos use workspace upload, exact CAS, and verified signed URLs", () => {
  assert.match(panel, /client\.uploadFile\(workspaceId, file, file\.name, file\.type\)/);
  assert.match(panel, /client\.addModelCommentPhoto\(target\.id, asset\.id, target\.revision\)/);
  assert.match(panel, /client\.removeModelCommentPhoto\(comment\.id, assetId, comment\.revision\)/);
  assert.match(panel, /client\.download\(assetId\)/);
  assert.match(panel, /result\.value\.asset_id === assetId/);
  assert.match(panel, /PHOTO_FORMATS\.has/);
  assert.match(panel, /result\.value\.byte_size > 0/);
  assert.match(panel, /safePhotoUrl\(result\.value\.url\)/);
  assert.match(panel, /photo_asset_ids \?\? \[\]\)\.length >= 10/);
});
