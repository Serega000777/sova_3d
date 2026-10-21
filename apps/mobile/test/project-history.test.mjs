import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("reference 60 uses the enriched immutable version-history API", () => {
  assert.match(project, /client\.listVersionHistory\(id\)/);
  assert.match(project, /details\?\.creator_name/);
  assert.match(project, /new Date\(version\.created_at\)\.toLocaleString\("ru-RU"\)/);
  assert.match(project, /formatAssetBytes\(details\?\.total_asset_bytes \?\? 0\)/);
});

test("mobile version comments preserve revision guarded server semantics", () => {
  assert.match(project, /details\.comment_revision/);
  assert.match(project, /client\.putVersionComment\(active\.id, versionCommentDraft, details\.comment_revision\)/);
  assert.match(project, /maxLength=\{2000\}/);
  assert.match(project, /Комментарий версии сохранён/);
});

test("history keeps comparison and append-only restore actions", () => {
  assert.match(project, /<VersionImageComparison/);
  assert.match(project, /client\.rollback\(/);
  assert.match(project, /Сделать v\{active\.sequence_no\} текущей/);
});
