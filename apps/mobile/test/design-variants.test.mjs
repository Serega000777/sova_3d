import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const project = readFileSync(new URL("../app/project/[id].tsx", import.meta.url), "utf8");

test("design variants keep one immutable source across regeneration", () => {
  assert.match(project, /const sourceVersion = variants\.length \? variantSourceVersion : active/);
  assert.match(project, /variants\.map\(\(variant\) => client\.discardVersion\(variant\.version\.id\)\)/);
  assert.match(project, /project_version_id: sourceVersion\?\.id \?\? null/);
  assert.match(project, /setVariantSourceVersion\(sourceVersion\)/);
  assert.match(project, /setVariantSourceVersion\(null\)/);
});

test("every built draft requests a canonical server thumbnail and remains 3D-selectable", () => {
  assert.match(project, /\.versionThumbnailUrls\(version\.id, version\.assets\)/);
  assert.match(project, /thumbnailUrl: thumbnailUrls\.iso \?\? thumbnailUrls\.front \?\? null/);
  assert.match(project, /source=\{\{ uri: variant\.thumbnailUrl \}\}/);
  assert.match(project, /onPress=\{\(\) => setActive\(variant\.version\)\}/);
  assert.match(project, /chooseVariant\(variant\.version\)/);
});
