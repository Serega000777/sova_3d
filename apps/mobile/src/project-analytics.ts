import type { IntegrityReport, Project } from "@physical-ai/contracts";

export interface ProjectActivityDay {
  day: string;
  updatedProjects: number;
}

export interface ProjectAnalytics {
  totalProjects: number;
  modelsCreated: number;
  drafts: number;
  updatedInWindow: number;
  activity: ProjectActivityDay[];
  mostRecent: Project | null;
}

export interface ProjectIntegrityAnalytics {
  modelHeads: number;
  checked: number;
  passed: number;
  warnings: number;
  failed: number;
  notChecked: number;
}

export function buildProjectIntegrityAnalytics(
  projects: readonly Project[],
  statusByVersion: ReadonlyMap<string, IntegrityReport["status"]>,
): ProjectIntegrityAnalytics {
  const heads = projects.flatMap((project) => (
    project.head_version_id ? [project.head_version_id] : []
  ));
  let passed = 0;
  let warnings = 0;
  let failed = 0;
  for (const versionId of heads) {
    const status = statusByVersion.get(versionId);
    if (status === "pass") passed += 1;
    else if (status === "warn") warnings += 1;
    else if (status === "fail") failed += 1;
  }
  const checked = passed + warnings + failed;
  return {
    modelHeads: heads.length,
    checked,
    passed,
    warnings,
    failed,
    notChecked: heads.length - checked,
  };
}

export function projectAnalyticsReport(
  analytics: ProjectAnalytics,
  snapshotMs: number,
  integrity?: ProjectIntegrityAnalytics,
): string {
  const snapshot = new Date(snapshotMs);
  if (!Number.isFinite(snapshot.getTime())) throw new Error("analytics snapshot time must be valid");
  const activeDays = analytics.activity
    .filter((item) => item.updatedProjects > 0)
    .map((item) => `${item.day}: ${item.updatedProjects}`);
  return [
    "Sova 3D — аналитика проектов",
    `Снимок: ${snapshot.toISOString()}`,
    "Источник: текущий канонический список проектов рабочего пространства.",
    "",
    `Всего проектов: ${analytics.totalProjects}`,
    `С текущей моделью: ${analytics.modelsCreated}`,
    `Черновиков без модели: ${analytics.drafts}`,
    `Обновлялись за 30 дней: ${analytics.updatedInWindow}`,
    analytics.mostRecent
      ? `Последний активный проект: ${analytics.mostRecent.name} (${analytics.mostRecent.id})`
      : "Последний активный проект: нет",
    "",
    ...(integrity ? [
      "Проверки текущих head-версий:",
      `Проверено: ${integrity.checked} из ${integrity.modelHeads}`,
      `Без ошибок: ${integrity.passed}`,
      `С замечаниями: ${integrity.warnings}`,
      `Не прошли: ${integrity.failed}`,
      `Без сохранённого отчёта: ${integrity.notChecked}`,
      "",
    ] : []),
    "Активность по дням с обновлениями:",
    ...(activeDays.length > 0 ? activeDays : ["нет обновлений"]),
    "",
    "Отчёт не вычисляет статус завершения или процент успешных проверок.",
  ].join("\n");
}

const DAY_MS = 24 * 60 * 60 * 1000;

function utcDay(timestamp: number): number {
  const date = new Date(timestamp);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

function projectTimestamp(project: Project): number | null {
  const timestamp = Date.parse(project.updated_at ?? project.created_at);
  return Number.isFinite(timestamp) ? timestamp : null;
}

/**
 * Builds only statistics supported by the canonical project list. In particular, this does not
 * infer project completion or aggregate integrity-check percentages: neither is present in
 * ProjectOut today.
 */
export function buildProjectAnalytics(
  projects: Project[],
  nowMs: number,
  windowDays = 30,
): ProjectAnalytics {
  const days = Math.max(1, Math.trunc(windowDays));
  const today = utcDay(nowMs);
  const firstDay = today - (days - 1) * DAY_MS;
  const activity = Array.from({ length: days }, (_, index) => ({
    day: new Date(firstDay + index * DAY_MS).toISOString().slice(0, 10),
    updatedProjects: 0,
  }));
  const activityByDay = new Map(activity.map((item) => [item.day, item]));
  let updatedInWindow = 0;
  let mostRecent: Project | null = null;
  let mostRecentTimestamp = Number.NEGATIVE_INFINITY;

  for (const project of projects) {
    const timestamp = projectTimestamp(project);
    if (timestamp === null) continue;
    if (timestamp <= nowMs && timestamp > mostRecentTimestamp) {
      mostRecentTimestamp = timestamp;
      mostRecent = project;
    }
    const projectDay = utcDay(timestamp);
    if (projectDay < firstDay || projectDay > today) continue;
    updatedInWindow += 1;
    const bucket = activityByDay.get(new Date(projectDay).toISOString().slice(0, 10));
    if (bucket) bucket.updatedProjects += 1;
  }

  const modelsCreated = projects.filter((project) => project.head_version_id !== null).length;
  return {
    totalProjects: projects.length,
    modelsCreated,
    drafts: projects.length - modelsCreated,
    updatedInWindow,
    activity,
    mostRecent,
  };
}
