import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const card = readFileSync(new URL("../src/components/ProjectDashboardCard.tsx", import.meta.url), "utf8");
const studio = readFileSync(new URL("../src/app/projects/[id]/page.tsx", import.meta.url), "utf8");

test("reference 70 web dashboard uses canonical version workspace and integrity facts", () => {
  assert.match(card, /listWorkspaceMembers\(project\.workspace_id\)/);
  assert.match(card, /getLatestIntegrityReport\(version\.id\)/);
  assert.match(card, /verifiedPersistedModelCheck\(record\)/);
  assert.match(card, /version\?\.assets\.some/);
});

test("dashboard refuses an invented readiness percentage and keeps errors local", () => {
  assert.match(card, /no invented readiness percentage/);
  assert.doesNotMatch(card, /readiness_pct|completion_pct/);
  assert.match(card, /\.catch\(\(\) => undefined\)/);
  assert.match(card, /reason instanceof ApiError && reason\.status === 404/);
});

test("studio mounts exact-version dashboard actions and prefers persisted thumbnail angles", () => {
  assert.match(studio, /tool === "dashboard"/);
  assert.match(studio, /versionThumbnailUrls\[activeVersion\.id\]\?\.iso/);
  assert.match(studio, /setTool\("integrity"\)/);
  assert.match(studio, /setTool\("comments"\)/);
  assert.match(studio, /setTool\("versions"\)/);
  assert.match(studio, /setTool\("export"\)/);
});
