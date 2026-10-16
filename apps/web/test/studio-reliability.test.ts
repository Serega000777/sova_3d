import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../src/app/projects/[id]/page.tsx", import.meta.url),
  "utf8",
);

test("Studio messages render once at shell level and remain dismissible", () => {
  const banner = page.indexOf('className="studio-messages"');
  const panel = page.indexOf("{tool && (");
  const chat = page.indexOf('{tool === "chat" && (');

  assert.ok(banner > 0);
  assert.ok(panel > banner);
  assert.ok(chat > panel);
  assert.equal(page.match(/className="studio-messages"/g)?.length, 1);
  assert.match(page, /onClick=\{\(\) => setError\(null\)\}/);
  assert.match(page, /onClick=\{\(\) => setNotice\(null\)\}/);
});

test("failed facade-opening hydration releases the apply gate and reports the error", () => {
  assert.match(
    page,
    /hydrateFacadeOpenings[\s\S]*?\.catch\(\(reason: unknown\) => \{[\s\S]*?setFacadeOpeningsHydrating\(false\);[\s\S]*?setError\(/,
  );
});

test("background refresh resolves visible linked thumbnails without generating jobs", () => {
  const refreshStart = page.indexOf("const refresh = useCallback");
  const refreshEnd = page.indexOf("refreshRef.current = refresh", refreshStart);
  const refresh = page.slice(refreshStart, refreshEnd);

  assert.ok(refreshStart > 0 && refreshEnd > refreshStart);
  assert.doesNotMatch(refresh, /versionThumbnailUrls\(/);
  assert.match(refresh, /visibleThumbnailVersions\.current\.has\(version\.id\)/);
  assert.match(refresh, /resolveVersionThumbnails\(version, false\)/);
});

test("thumbnail loading is visibility-bound and merges into the existing URL map", () => {
  assert.match(page, /new IntersectionObserver/);
  assert.match(page, /resolveVersionThumbnails\(version, true\)/);
  assert.match(page, /\[version\.id\]: \{ \.\.\.current\[version\.id\], \.\.\.urls \}/);
  assert.match(page, /<LazyVersionThumbnail/);
});
