import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildProjectAnalytics,
  buildProjectIntegrityAnalytics,
  projectAnalyticsReport,
} from "../src/lib/project-analytics.ts";

const now = Date.parse("2026-11-05T12:00:00Z");
const projects = [
  { id: "recent", name: "Recent", head_version_id: "v1", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-11-05T10:00:00Z" },
  { id: "draft", name: "Draft", head_version_id: null, created_at: "2026-11-04T00:00:00Z", updated_at: null },
  { id: "future", name: "Future", head_version_id: "v2", created_at: "2026-11-06T00:00:00Z", updated_at: null },
] as never;

test("analytics uses canonical project timestamps without counting future rows", () => {
  const result = buildProjectAnalytics(projects, now);
  assert.equal(result.totalProjects, 3);
  assert.equal(result.modelsCreated, 2);
  assert.equal(result.drafts, 1);
  assert.equal(result.updatedInWindow, 2);
  assert.equal(result.mostRecent?.id, "recent");
  assert.equal(result.activity.reduce((sum, item) => sum + item.updatedProjects, 0), 2);
});

test("integrity totals count only persisted statuses for exact heads", () => {
  const result = buildProjectIntegrityAnalytics(projects, new Map([["v1", "warn"]]));
  assert.deepEqual(result, { modelHeads: 2, checked: 1, passed: 0, warnings: 1, failed: 0, notChecked: 1 });
});

test("text snapshot reports facts and never invents completion", () => {
  const analytics = buildProjectAnalytics(projects, now);
  const report = projectAnalyticsReport(analytics, now);
  assert.match(report, /Всего проектов: 3/);
  assert.match(report, /не вычисляет статус завершения/);
  assert.doesNotMatch(report, /96%|завершено: [1-9]/i);
});

test("web route binds all supplemental data to the selected workspace and degrades locally", () => {
  const page = readFileSync(new URL("../src/app/analytics/page.tsx", import.meta.url), "utf8");
  const library = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /const workspaceId = session\.workspaceId/);
  assert.match(page, /client\.listProjects\(workspaceId\)/);
  assert.match(page, /client\.listWorkspaceVersionActivity\(workspaceId, 30\)/);
  assert.match(page, /client\.getLatestIntegrityReport\(versionId\)/);
  assert.match(page, /reason instanceof ApiError && reason\.status === 404/);
  assert.match(page, /loadRevision\.current !== request/);
  assert.match(page, /setIntegrityError/);
  assert.match(page, /setActivityError/);
  assert.match(page, /ordinaryModelCheckStatus/);
  assert.match(library, /href="\/analytics"/);
});
