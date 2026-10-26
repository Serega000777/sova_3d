import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildProjectAnalytics, projectAnalyticsReport } from "../src/project-analytics.ts";

const project = (id, updatedAt, headVersionId = null) => ({
  id,
  workspace_id: "workspace",
  name: `Проект ${id}`,
  description: null,
  units: "mm",
  head_version_id: headVersionId,
  created_at: updatedAt,
  updated_at: updatedAt,
});

test("project analytics derives honest workspace totals and 30-day activity", () => {
  const analytics = buildProjectAnalytics(
    [
      project("recent-model", "2026-10-22T08:00:00Z", "version-1"),
      project("recent-draft", "2026-10-21T12:00:00Z"),
      project("old-model", "2026-09-01T12:00:00Z", "version-2"),
    ],
    Date.parse("2026-10-22T12:00:00Z"),
  );

  assert.equal(analytics.totalProjects, 3);
  assert.equal(analytics.modelsCreated, 2);
  assert.equal(analytics.drafts, 1);
  assert.equal(analytics.updatedInWindow, 2);
  assert.equal(analytics.activity.length, 30);
  assert.equal(analytics.activity.at(-1)?.updatedProjects, 1);
  assert.equal(analytics.activity.at(-2)?.updatedProjects, 1);
  assert.equal(analytics.mostRecent?.id, "recent-model");
});

test("future and malformed timestamps do not inflate the reporting window", () => {
  const analytics = buildProjectAnalytics(
    [project("future", "2026-10-23T00:00:00Z"), project("invalid", "not-a-date")],
    Date.parse("2026-10-22T12:00:00Z"),
  );

  assert.equal(analytics.totalProjects, 2);
  assert.equal(analytics.updatedInWindow, 0);
  assert.equal(analytics.activity.reduce((sum, item) => sum + item.updatedProjects, 0), 0);
  assert.equal(analytics.mostRecent, null);
});

test("analytics report exports only the same canonical project-list facts", () => {
  const snapshotMs = Date.parse("2026-10-22T12:00:00Z");
  const analytics = buildProjectAnalytics(
    [project("recent-model", "2026-10-22T08:00:00Z", "version-1")],
    snapshotMs,
  );
  const report = projectAnalyticsReport(analytics, snapshotMs);

  assert.match(report, /Снимок: 2026-10-22T12:00:00\.000Z/);
  assert.match(report, /Всего проектов: 1/);
  assert.match(report, /С текущей моделью: 1/);
  assert.match(report, /2026-10-22: 1/);
  assert.match(report, /Проект recent-model \(recent-model\)/);
  assert.match(report, /не вычисляет статус завершения или процент успешных проверок/);
  assert.doesNotMatch(report, /96%|завершено|успешных проверок: [0-9]/);
});

test("mobile projects route exposes analytics without invented completion metrics", () => {
  const projectsSource = readFileSync(new URL("../app/(tabs)/projects.tsx", import.meta.url), "utf8");
  const analyticsSource = readFileSync(new URL("../app/analytics.tsx", import.meta.url), "utf8");

  assert.match(projectsSource, /router\.push\("\/analytics"\)/);
  assert.match(analyticsSource, /client\.listProjects\(session\.workspaceId\)/);
  assert.match(analyticsSource, /Share\.share\(\{ message: projectAnalyticsReport/);
  assert.match(analyticsSource, /не показывает выдуманный процент/);
  assert.doesNotMatch(analyticsSource, /96%|8 завершено|12 моделей создано/);
});
