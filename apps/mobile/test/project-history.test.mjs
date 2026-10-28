import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");
const historyScreen = readFileSync(new URL("../app/project-history/[id].tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("../app/_layout.tsx", import.meta.url), "utf8");

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

test("reference 60 opens a dedicated full-screen project timeline", () => {
  assert.match(layout, /name="project-history\/\[id\]"/);
  assert.match(project, /router\.push\(`\/project-history\/\$\{id\}`\)/);
  assert.match(historyScreen, /accessibilityLabel="История изменений проекта"/);
  assert.match(historyScreen, /flexDirection: isTablet \? "row" : "column"/);
  assert.match(historyScreen, /client\.listVersionHistory\(id\)/);
});

test("full-screen history keeps canonical previews, comparison, comments, and immutable restore", () => {
  assert.match(historyScreen, /\.versionThumbnailUrls\(version\.id, version\.assets\)/);
  assert.match(historyScreen, /<VersionImageComparison/);
  assert.match(historyScreen, /client\.putVersionComment\(selected\.id, comment, selected\.comment_revision\)/);
  assert.match(historyScreen, /client\.rollback\(/);
  assert.match(historyScreen, /project\?\.head_version\?\.id \?\? null/);
  assert.match(historyScreen, /создаст новую версию поверх текущей/);
});

test("G09 distinguishes the viewed version from the current project head", () => {
  assert.match(project, /const isSelected = version\.id === active\?\.id/);
  assert.match(project, /const isHead = version\.id === project\?\.head_version\?\.id/);
  assert.match(project, /accessibilityState=\{\{ selected: isSelected \}\}/);
  assert.match(project, /isHead \? \(ru \? ", текущая" : ", current"\)/);
  assert.match(project, /\{ru \? "ТЕКУЩАЯ" : "CURRENT"\}/);
  assert.match(project, /active\.id !== project\.head_version\.id/);
  assert.match(project, /Сделать v\{active\.sequence_no\} текущей/);
});
